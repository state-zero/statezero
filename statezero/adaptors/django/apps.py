import importlib
import logging
import os

from django.apps import AppConfig as DjangoAppConfig
from django.apps import apps
from django.conf import settings

from statezero.adaptors.django.config import config, registry

# Attempt to import Rich for nicer console output.
try:
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
except ImportError:
    console = None

logger = logging.getLogger(__name__)


class StateZeroDjangoConfig(DjangoAppConfig):
    name = "statezero.adaptors.django"
    verbose_name = "StateZero Django Integration"

    def ready(self):
        # Import crud modules which register models in the registry.
        if hasattr(settings, 'CONFIG_FILE_PREFIX'):
            config_file_prefix: str = settings.CONFIG_FILE_PREFIX
            config_file_prefix = config_file_prefix.replace('.py', '')
            if (not isinstance(config_file_prefix, str)) or (len(config_file_prefix) < 1):
                raise ValueError(f"If provided, CONFIG_FILE_PREFIX must be a string with at least one character. In your settings.py it is set to {settings.CONFIG_FILE_PREFIX}. Either delete the setting completely or use a valid file name like 'crud'")
        else:
            config_file_prefix = "crud"
        for app_config_instance in apps.get_app_configs():
            module_name = f"{app_config_instance.name}.{config_file_prefix}"
            try:
                importlib.import_module(module_name)
                logger.debug(f"Imported {config_file_prefix} module from {app_config_instance.name}")
            except ModuleNotFoundError:
                pass

        # Once all the apps are imported, initialize StateZero and provide the registry to the event bus.
        config.initialize()
        config.validate_exposed_models(registry) # Raises an exception if a non StateZero model is implicitly exposed
        config.event_bus.set_registry(registry)

        # Print the list of published models (from registry) to confirm StateZero is running.
        try:
            published_models = []
            for model in registry._models_config.keys():
                # Use the ORM provider's get_model_name to get the namespaced model name.
                model_name = model.__name__
                published_models.append(model_name)

            if published_models:
                base_message = (
                    "[bold green]StateZero is exposing models:[/bold green] [bold yellow]"
                    + ", ".join(published_models)
                    + "[/bold yellow]"  
                )
            else:
                base_message = "[bold yellow]StateZero is running but no models are registered.[/bold yellow]"

            # Append the npm command instruction only in debug mode.
            if published_models and settings.DEBUG:
                npm_message = (
                    "\n[bold blue]Next step:[/bold blue] Run [italic]npm run sync-models[/italic] in your frontend project directory "
                    "to generate or update the client-side code corresponding to these models. "
                    "Note: This command should only be executed in a development environment."
                )
                message = base_message + npm_message
            else:
                message = base_message

            # Use Rich Panel for a boxed display if Rich is available.
            if console:
                final_message = Panel(message, expand=False)
                console.print(final_message)
            else:
                # Fallback to simple demarcation lines if Rich isn't available.
                demarcation = "\n" + "-" * 50 + "\n"
                final_message = demarcation + message + demarcation
                logger.info(final_message)
        except Exception as e:
            error_message = (
                f"[bold red]Error retrieving published models: {e}[/bold red]"
            )
            if console:
                final_message = Panel(error_message, expand=False)
                console.print(final_message)
            else:
                demarcation = "\n" + "-" * 50 + "\n"
                final_message = demarcation + error_message + demarcation
                logger.info(final_message)
