from app.rag.rail_index import ExactMessageIndex


def init(app):
    # Input-only rails do not use semantic dialogue matching. Register an exact
    # lookup for the runtime's static system messages to avoid an unused ML model.
    app.register_embedding_search_provider("exact_message_lookup", ExactMessageIndex)
