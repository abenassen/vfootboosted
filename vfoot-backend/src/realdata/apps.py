from django.apps import AppConfig


class RealdataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'realdata'

    def ready(self):
        # Opt-in, DEBUG-only, runserver-only: every guard lives in the module, which
        # also says why each one is there. Without VFOOT_TICK_IN_PROCESS this is a
        # no-op, so the normal path — a separate tick process, or the systemd timer
        # in production — is untouched.
        from realdata.services.tick_thread import start_if_requested

        start_if_requested()
