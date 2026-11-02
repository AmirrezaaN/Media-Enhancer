from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download every AI model so the first job does not have to wait for downloads."

    def handle(self, *args, **options):
        from mecore import weights

        from enhancer.ai import create_engine, engine_config

        config = engine_config()
        for name in weights.MODELS:
            path = weights.ensure(config.weights_dir, name)
            self.stdout.write(f"  {name}: {path.stat().st_size / 1e6:.1f} MB")

        engine = create_engine()
        self.stdout.write("Loading face detection / parsing models...")
        engine.faces()
        self.stdout.write("Loading frame interpolation model (RIFE)...")
        engine.interpolator()
        self.stdout.write(self.style.SUCCESS("All models are ready."))
