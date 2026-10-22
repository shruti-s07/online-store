from backend.shared.errors import DomainError


class ModelNotTrained(DomainError):
    status_code = 503
    default_code = "model_not_trained"

    def __init__(self, name: str):
        super().__init__(f"The {name} model has not been trained yet. Run: python store.py train", model=name)
