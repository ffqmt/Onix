import os


class Config(object):
    basedir = os.path.abspath(os.path.dirname(__file__))
    SECRET_KEY = os.getenv('SECRET_KEY', '0]C&1?s~r?YZ{]0f]V:,PL;.Oho48CFf%fP[r/XV#?!Z.$sX{/~nPs=yuFbOrPo')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'onixTestDB.sqlite3')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ASSETS_ROOT = os.getenv('ASSETS_ROOT', 'STATIC/assets')


class ProductionConfig(Config):
    DEBUG = False
    # Security
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = 3600


class DebugConfig(Config):
    DEBUG = True


config_dict = {
    'Production': ProductionConfig,
    'Debug': DebugConfig
}
