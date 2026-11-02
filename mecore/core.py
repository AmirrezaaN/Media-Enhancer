"""GPU models: super-resolution (Real-ESRGAN), face restoration (GFPGAN) and frame interpolation (RIFE)."""

import copy
import logging
import warnings

import numpy as np
import torch
import torch.nn.functional as F
from spandrel import ImageModelDescriptor, ModelLoader

from . import weights
from .config import EngineConfig

logger = logging.getLogger("mecore")

# facexlib still uses the old torchvision "pretrained" argument; the warning is harmless.
warnings.filterwarnings("ignore", category=UserWarning, module="torchvision.models._utils")

FAST_MODEL = "realesr-general-x4v3"
HIGH_MODEL_X4 = "RealESRGAN_x4plus"
HIGH_MODEL_X2 = "RealESRGAN_x2plus"
CHANNELS_LAST = True


def to_tensor(rgb: np.ndarray, device, dtype) -> torch.Tensor:
    """HWC uint8 RGB numpy -> 1x3xHxW float tensor in [0, 1]."""
    if not rgb.flags.writeable or not rgb.flags.c_contiguous:
        rgb = np.array(rgb, copy=True, order="C")
    t = torch.from_numpy(rgb).to(device)
    return t.permute(2, 0, 1).unsqueeze(0).to(dtype).div_(255.0)


def to_numpy(t: torch.Tensor) -> np.ndarray:
    """1x3xHxW float tensor in [0, 1] -> HWC uint8 RGB numpy."""
    return t.clamp(0, 1).mul(255.0).round_().to(torch.uint8).squeeze(0).permute(1, 2, 0).contiguous().cpu().numpy()


def resize_tensor(t: torch.Tensor, height: int, width: int) -> torch.Tensor:
    _, _, h, w = t.shape
    if (h, w) == (height, width):
        return t
    out = F.interpolate(t.float(), size=(height, width), mode="bicubic", antialias=True, align_corners=False)
    return out.clamp_(0, 1).to(t.dtype)


class Upscaler:
    """Runs a super-resolution model, splitting big inputs into overlapping tiles.

    Half precision is faster, but some GPUs (hot, overclocked or with driver issues) occasionally
    return garbage for a tile, which shows up as black blobs or striped blocks. Every half-precision
    tile is therefore checked against its input and redone in full precision when it does not match.
    In testing on an affected GPU about 1% of half-precision tiles were corrupt and all of them were
    caught, so this keeps nearly the full speed of half precision without the artifacts.
    """

    TILE_PAD = 16
    # A tile is corrupt when, after shrinking it back to the input size, at least GUARD_MIN_PIXELS
    # pixels differ from the input by more than GUARD_THRESHOLD (0-1 scale). Calibrated on real footage:
    # no correct tile came close (worst: 1 pixel above 0.4), every corrupted tile was far above.
    GUARD_THRESHOLD = 0.45
    GUARD_MIN_PIXELS = 2

    def __init__(self, name: str, config: EngineConfig, device: torch.device, tile: int, half: bool):
        path = weights.ensure(config.weights_dir, name)
        descriptor = ModelLoader(device=device).load_from_file(str(path))
        if not isinstance(descriptor, ImageModelDescriptor):
            raise RuntimeError(f"{name} is not an image model")
        descriptor.eval()
        self.full = descriptor
        self.half = bool(half and device.type == "cuda" and descriptor.supports_half)
        if self.half:
            self.model = copy.deepcopy(descriptor).half()
        else:
            self.model = descriptor
        self.name = name
        self.scale = descriptor.scale
        self.tile = tile
        self.device = device
        self.dtype = torch.float16 if self.half else torch.float32
        self.repaired_tiles = 0
        # NHWC ("channels last") lets cuDNN use the tensor cores without extra transposes: about 25%
        # faster in half precision (and it produced far fewer GPU errors in testing). In full precision
        # it is slower, so it is only used for half-precision models.
        self.channels_last = device.type == "cuda" and CHANNELS_LAST and self.half
        if self.channels_last:
            for desc in {id(self.model): self.model, id(self.full): self.full}.values():
                desc.model.to(memory_format=torch.channels_last)

    def _corrupt(self, x: torch.Tensor, y: torch.Tensor) -> bool:
        if not torch.isfinite(y).all():
            return True
        down = F.avg_pool2d(y.float(), self.scale) if self.scale > 1 else y.float()
        diff = (down - x.float()).abs().amax(dim=1)
        return int((diff > self.GUARD_THRESHOLD).sum()) >= self.GUARD_MIN_PIXELS

    def _infer(self, x: torch.Tensor) -> torch.Tensor:
        if self.channels_last:
            x = x.contiguous(memory_format=torch.channels_last)
        y = self.model(x)
        if self.half and self._corrupt(x, y):
            self.repaired_tiles += 1
            logger.warning("%s: corrupt half-precision tile detected, recomputing in full precision", self.name)
            y = self.full(x.float()).to(y.dtype)
        return y

    @torch.inference_mode()
    def __call__(self, x: torch.Tensor, on_progress=None) -> torch.Tensor:
        while True:
            try:
                return self._run(x, self.tile, on_progress)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                current = self.tile or max(x.shape[-2:])
                if current <= 128:
                    raise
                self.tile = max(128, current // 2)
                logger.warning("Out of GPU memory, retrying %s with tile size %d", self.name, self.tile)

    def _run(self, x, tile, on_progress):
        _, _, h, w = x.shape
        if not tile or (h <= tile and w <= tile):
            out = self._infer(x)
            if on_progress:
                on_progress(1.0)
            return out

        s, pad = self.scale, self.TILE_PAD
        out = x.new_zeros((1, 3, h * s, w * s))
        ys, xs = range(0, h, tile), range(0, w, tile)
        total, done = len(ys) * len(xs), 0
        for y0 in ys:
            for x0 in xs:
                y1, x1 = min(y0 + tile, h), min(x0 + tile, w)
                py0, px0 = max(y0 - pad, 0), max(x0 - pad, 0)
                py1, px1 = min(y1 + pad, h), min(x1 + pad, w)
                tile_out = self._infer(x[:, :, py0:py1, px0:px1])
                oy, ox = (y0 - py0) * s, (x0 - px0) * s
                out[:, :, y0 * s:y1 * s, x0 * s:x1 * s] = tile_out[
                    :, :, oy:oy + (y1 - y0) * s, ox:ox + (x1 - x0) * s
                ]
                done += 1
                if on_progress:
                    on_progress(done / total)
        return out


class FaceRestorer:
    """Detects faces, restores them with GFPGAN v1.4 and pastes them back into the upscaled image."""

    def __init__(self, config: EngineConfig, device: torch.device):
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper

        descriptor = ModelLoader(device=device).load_from_file(str(weights.ensure(config.weights_dir, "GFPGANv1.4")))
        # GFPGAN always runs in full precision: faces are small, so it is cheap.
        self.net = descriptor.model.eval()
        self.device = device
        self.helper = FaceRestoreHelper(
            upscale_factor=1,
            face_size=512,
            crop_ratio=(1, 1),
            det_model="retinaface_resnet50",
            save_ext="png",
            use_parse=True,
            device=device,
            model_rootpath=str(config.weights_dir / "facexlib"),
        )

    @torch.inference_mode()
    def enhance(self, source_rgb: np.ndarray, upscaled_rgb: np.ndarray) -> np.ndarray:
        """Return upscaled_rgb with every detected face restored. Sizes are preserved."""
        out_h, out_w = upscaled_rgb.shape[:2]
        helper = self.helper
        helper.clean_all()
        helper.set_upscale_factor(out_w / source_rgb.shape[1])
        helper.read_image(np.ascontiguousarray(source_rgb[:, :, ::-1]))
        helper.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
        if not helper.all_landmarks_5:
            return upscaled_rgb
        helper.align_warp_face()
        for face_bgr in helper.cropped_faces:
            t = torch.from_numpy(np.ascontiguousarray(face_bgr[:, :, ::-1])).to(self.device)
            t = t.permute(2, 0, 1).unsqueeze(0).float().div(255.0).mul(2).sub(1)
            restored = self.net(t, return_rgb=False)[0]
            restored = restored.clamp(-1, 1).add(1).div(2).mul(255).round().to(torch.uint8)
            restored = restored.squeeze(0).permute(1, 2, 0).cpu().numpy()[:, :, ::-1]
            helper.add_restored_face(np.ascontiguousarray(restored))
        helper.get_inverse_affine(None)
        result_bgr = helper.paste_faces_to_input_image(upsample_img=np.ascontiguousarray(upscaled_rgb[:, :, ::-1]))
        result = np.ascontiguousarray(result_bgr[:, :, ::-1]).astype(np.uint8)
        if result.shape[:2] != (out_h, out_w):
            import cv2

            result = cv2.resize(result, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        return result


class Interpolator:
    """RIFE v4.26 frame interpolation: creates the frame halfway between two frames."""

    SCENE_CUT_THRESHOLD = 0.12

    def __init__(self, config: EngineConfig, device: torch.device, half: bool):
        from ccvfi import AutoModel, ConfigType

        self.model = AutoModel.from_pretrained(
            ConfigType.RIFE_IFNet_v426_heavy,
            device=device,
            fp16=half,
            model_dir=str(config.weights_dir),
        )
        self.dtype = torch.float16 if self.model.fp16 else torch.float32

    @staticmethod
    def _small_gray(t):
        return F.interpolate(t.float().mean(dim=1, keepdim=True), size=(64, 64), mode="area")

    @torch.inference_mode()
    def middle(self, a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        # On a scene cut, blending two unrelated pictures looks bad: repeat the first one instead.
        if (self._small_gray(a) - self._small_gray(b)).abs().mean().item() > self.SCENE_CUT_THRESHOLD:
            return a
        side = max(a.shape[-2:])
        flow_scale = 1.0 if side <= 1920 else 0.5 if side <= 3840 else 0.25
        imgs = torch.stack([a.to(self.dtype), b.to(self.dtype)], dim=1)
        mid = self.model.inference(imgs, timestep=0.5, scale=flow_scale)
        if not torch.isfinite(mid).all():
            # Same safety net as the upscaler: never let a broken frame through.
            mid = (a.float() + b.float()).mul_(0.5)
        return mid.clamp_(0, 1).to(a.dtype)


class Engine:
    """Lazily loads models once and keeps them on the GPU between jobs."""

    def __init__(self, config: EngineConfig):
        self.config = config
        if config.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("No NVIDIA GPU (CUDA) is available. Check the NVIDIA driver.")
        self.device = torch.device(config.device)
        self.cuda = self.device.type == "cuda"
        self.device_name = torch.cuda.get_device_name(self.device) if self.cuda else "CPU"
        if self.cuda:
            torch.backends.cudnn.benchmark = True
            # Let full-precision convolutions/matmuls use the tensor cores (TF32) on Ampere and newer.
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cuda.matmul.allow_tf32 = True
        self._upscalers = {}
        self._faces = None
        self._interpolator = None

    def uses_half(self, name: str) -> bool:
        """Precision policy for the upscalers.

        auto/fp16: half precision (about twice as fast as full precision here), every tile checked by
                   the corruption guard and redone in full precision when it is bad.
        fp32:      everything in full precision (slowest, for GPUs that fail the check very often).
        """
        return self.cuda and self.config.precision != "fp32"

    def upscaler(self, name: str) -> Upscaler:
        if name not in self._upscalers:
            # The compact model is light enough to run on whole HD frames.
            tile = 1280 if name == FAST_MODEL else self.config.tile_size
            self._upscalers[name] = Upscaler(name, self.config, self.device, tile, self.uses_half(name))
        return self._upscalers[name]

    def faces(self) -> FaceRestorer:
        if self._faces is None:
            self._faces = FaceRestorer(self.config, self.device)
        return self._faces

    def interpolator(self) -> Interpolator:
        if self._interpolator is None:
            # Half precision: at 4K full precision needs ~10 GB (more than most cards have, so Windows
            # spills to system RAM and it becomes ~15x slower). Broken frames are caught in middle().
            self._interpolator = Interpolator(self.config, self.device, self.cuda and self.config.precision != "fp32")
        return self._interpolator

    def repaired_tiles(self) -> int:
        return sum(u.repaired_tiles for u in self._upscalers.values())

    def free_memory(self):
        if self.cuda:
            torch.cuda.empty_cache()
