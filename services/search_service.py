import logging
from dataclasses import dataclass

from config import get_settings

logger = logging.getLogger("orion_light.search")

settings = get_settings()


@dataclass
class SearchResult:
    title: str
    body: str
    url: str


class SearchService:
    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        n = max_results or settings.SEARCH_MAX_RESULTS
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = ddgs.text(query, max_results=n, region="br-pt")
            return [
                SearchResult(
                    title=r.get("title", ""),
                    body=r.get("body", ""),
                    url=r.get("href", ""),
                )
                for r in (raw or [])
            ]
        except Exception as exc:
            logger.warning("Busca web falhou: %s", exc)
            return []

    def format_for_context(self, results: list[SearchResult]) -> str:
        if not results:
            return "Nenhum resultado encontrado na busca web."
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] {r.title}\n{r.body}\nFonte: {r.url}")
        return "\n\n".join(parts)


search_service = SearchService()
