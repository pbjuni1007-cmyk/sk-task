"""SQLite-backed LangGraph Store restricted to one server-owned actor namespace."""

from datetime import datetime, timezone

from langgraph.store.base import BaseStore, GetOp, Item, PutOp, SearchItem, SearchOp


class PreferenceStore(BaseStore):
    def __init__(self, service, context):
        self.service = service
        self.context = context

    def batch(self, ops):
        results = []
        for op in ops:
            namespace = getattr(op, "namespace", getattr(op, "namespace_prefix", ()))
            if tuple(namespace) != ("preferences", self.context.actor_id):
                raise PermissionError("STORE_NAMESPACE")
            value = self.service.get_preferences(self.context)
            if not value.ok:
                raise PermissionError("STORE_ACCESS")
            with self.service.db.transaction() as db:
                meta = db.execute(
                    "SELECT created_at,updated_at FROM preference_meta WHERE actor=?",
                    (self.context.actor_id,),
                ).fetchone()
            created = (
                datetime.fromisoformat(meta[0]) if meta else datetime.fromtimestamp(0, timezone.utc)
            )
            updated = datetime.fromisoformat(meta[1]) if meta else created
            if isinstance(op, GetOp):
                results.append(
                    Item(
                        value=value.data,
                        key="settings",
                        namespace=namespace,
                        created_at=created,
                        updated_at=updated,
                    )
                    if op.key == "settings" and value.data
                    else None
                )
            elif isinstance(op, SearchOp):
                if op.query or op.filter:
                    raise ValueError("STORE_FILTER_UNSUPPORTED")
                items = (
                    [
                        SearchItem(
                            value=value.data,
                            key="settings",
                            namespace=namespace,
                            created_at=created,
                            updated_at=updated,
                        )
                    ]
                    if value.data
                    else []
                )
                results.append(items[op.offset : op.offset + op.limit])
            elif isinstance(op, PutOp):
                # Writes must use the consent-aware service, never generic model Store access.
                raise PermissionError("USE_CONSENT_SERVICE")
            else:
                raise NotImplementedError("STORE_OPERATION")
        return results

    async def abatch(self, ops):
        return self.batch(ops)
