"""Flask entry point wiring for the subscription aggregator."""
from api.subscription_aggregator import create_flask_app

app = create_flask_app()

__all__ = ("app",)

if __name__ == "__main__":
    from api.subscription_aggregator.flask_app import main

    main()
