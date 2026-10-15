from nemoguardrails.embeddings.index import EmbeddingsIndex, IndexItem


class ExactMessageIndex(EmbeddingsIndex):
    """Exact lookup for static NeMo messages, independent of document retrieval.

    Semantic dialog rails are disabled. No text is embedded by this provider.
    The document pipeline continues to use MPNet and Elasticsearch.
    """

    def __init__(self, **kwargs):
        self.items: list[IndexItem] = []

    @property
    def embedding_size(self):
        return 0

    @property
    def cache_config(self):
        return None

    async def add_item(self, item: IndexItem):
        self.items.append(item)

    async def add_items(self, items: list[IndexItem]):
        self.items.extend(items)

    async def search(self, text: str, max_results: int, threshold=None):
        return [i for i in self.items if i.text.casefold() == text.casefold()][
            :max_results
        ]
