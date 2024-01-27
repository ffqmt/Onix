# -*- encoding: utf-8 -*-
# CONTEXT DO BANCO DE DADOS BY ONIX #
import os
from flask import Flask
from OnixWeb import db
from OnixWeb.config import config_dict

app = Flask(__name__)
DEBUG = (os.getenv('DEBUG', 'False') == 'True')
get_config_mode = 'Debug' if DEBUG else 'Production'
try:
    app_config = config_dict[get_config_mode.capitalize()]
except KeyError:
    exit('Error: Invalid <config_mode>. Expected values [Debug, Production] ')
app.config.from_object(app_config)
db.init_app(app)
