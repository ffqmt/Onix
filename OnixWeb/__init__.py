# -*- encoding: utf-8 -*-
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from importlib import import_module
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
db = SQLAlchemy()
login_manager = LoginManager()


class DataBase(object):
    db_initialized = False


def register_extensions(app):
    db.init_app(app)
    login_manager.init_app(app)


def register_blueprints(app):
    # REGISTRO BLUEPRINT AUTHENTICAÇÃO E ADICIONAIS (NÃO ADMIN)
    for module_name in ['authentication', 'aditional_routes']:
        module = import_module(f'OnixWeb.{module_name}.routes')
        app.register_blueprint(module.blueprint)


def configure_database(app):
    @app.before_request
    def initialize_database():
        if DataBase.db_initialized:
            pass
        else:
            db.create_all()
            DataBase.db_initialized = True

    @app.teardown_request
    def shutdown_session(exception=None):
        db.session.remove()


def create_app(config):
    app = Flask(__name__)
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    csrf.init_app(app)
    app.config.from_object(config)
    register_extensions(app)
    register_blueprints(app)
    configure_database(app)
    return app
