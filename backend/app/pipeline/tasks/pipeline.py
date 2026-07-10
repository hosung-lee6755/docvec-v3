from celery import Signature, chain

from app.pipeline.tasks.ingest import ingest_document
from app.pipeline.tasks.process import continue_processing, parse_document


def create_processing_chain(document_id: str, skip_review: bool = False) -> Signature:
    steps = [ingest_document.s(document_id), parse_document.s()]
    if skip_review:
        # .si() (immutable signature): parse_document returns a result dict, not a
        # document_id string, so continue_processing must ignore the chained input
        # and use the document_id bound here instead of positionally accepting it.
        steps.append(continue_processing.si(document_id))
    return chain(*steps)
