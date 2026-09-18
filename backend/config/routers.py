class ApplicationRouter:
    """The ORM owns only the application DB; WMS uses explicit SELECT queries."""

    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return obj1._state.db == obj2._state.db == "default"

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"
