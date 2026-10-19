from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download every AI model so the first job does not have to wait for downloads."

    def handle(self, *args, **options):
        from enhancer.engine import weights
        from enhancer.engine.core import Engine

        for name in weights.MODELS:
            path = weights.ensure(name)
            self.stdout.write(f"  {name}: {path.stat().st_size / 1e6:.1f} MB")

        engine = Engine()
        self.stdout.write("Loading face detection / parsing models...")
        engine.faces()
        self.stdout.write("Loading frame interpolation model (RIFE)...")
        engine.interpolator()
        self.stdout.write(self.style.SUCCESS("All models are ready."))
