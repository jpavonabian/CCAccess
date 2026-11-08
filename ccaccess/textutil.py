"""Utilidades de texto sin Qt."""
import unicodedata


def fold(text: str) -> str:
    """Minúsculas y sin tildes, para buscar «jose» y encontrar «José»."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
