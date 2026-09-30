def register_blueprints(app):
    from . import (admin, attendance, auth, dashboard, evaluations, imports, reports, review, selfservice, today,
                   users)
    for mod in (auth, dashboard, attendance, admin, imports, evaluations, review, reports, selfservice, today, users):
        app.register_blueprint(mod.bp)
