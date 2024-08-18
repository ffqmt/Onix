# -*- encoding: utf-8 -*-
import json

from flask_login import UserMixin
from OnixWeb import db, login_manager
from OnixWeb.addons.util import hash_pass
import os

root_path = os.path.abspath('')


class Empresas(db.Model):
    __tablename__ = 'Empresas'

    id = db.Column(db.Integer, primary_key=True)
    cnpj = db.Column(db.String(64), unique=True)
    chave_acesso = db.Column(db.String(64))
    login_contabilista = db.Column(db.String(64))
    senha_contabilista = db.Column(db.String(64))
    nome = db.Column(db.String(64), nullable=False)
    base64logo = db.Column(db.LargeBinary(), nullable=False)
    licensed_until = db.Column(db.DateTime())
    autorizado_schedule = db.Column(db.Integer, default=0)
    receiver_ip = db.Column(db.String(64))
    receiver_ip_secondary = db.Column(db.String(64))
    receiver_port = db.Column(db.Integer)

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            if property == 'desc_parameter':
                value = str(value)

            setattr(self, property, value)


class Users(db.Model, UserMixin):
    __tablename__ = 'Users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True)
    realname = db.Column(db.String(64))
    password = db.Column(db.LargeBinary)  # LARGEBINARY PARA ENCRYPTED
    id_empresa = db.Column(db.String(64), db.ForeignKey('Empresas.id'), unique=True)
    setor = db.Column(db.String(64))
    admin = db.Column(db.Integer)

    # RELAÇÕES
    empresa = db.relationship('Empresas')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            if property == 'password':
                value = hash_pass(value)  # valores em bytes (tipo de coluna da senha)

            setattr(self, property, value)

    def __repr__(self):
        return str(self.username)


@login_manager.user_loader
def user_loader(id):
    return Users.query.filter_by(id=id).first()


@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    user = Users.query.filter_by(username=username).first()
    return user if user else None


class ConfigParameters(db.Model):
    __tablename__ = 'ConfigParameters'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    parameter = db.Column(db.String(6), unique=True)
    value = db.Column(db.Integer)
    desc_parameter = db.Column(db.String(64))

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            if property == 'desc_parameter':
                value = str(value)

            setattr(self, property, value)


class PessoaJuridica(db.Model):
    __tablename__ = 'PessoaJuridica'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    id_empresa = db.Column(db.Integer, db.ForeignKey('Empresas.id'))
    name = db.Column(db.String(80))
    cnpj_cpf = db.Column(db.String(14))
    ie = db.Column(db.Integer)
    id_city = db.Column(db.Integer, db.ForeignKey('City.id'))
    password = db.Column(db.String(64))
    pref_enc_tomado = db.Column(db.Integer, default=0)
    pref_enc_prestado = db.Column(db.Integer, default=0)
    pref_guia_issqn = db.Column(db.Integer, default=0)
    pref_rel_tomado = db.Column(db.Integer, default=0)
    pref_rel_prestado = db.Column(db.Integer, default=0)
    pref_nfe_tomado = db.Column(db.Integer, default=0)
    pref_nfe_prestado = db.Column(db.Integer, default=0)
    sefaz_nfe_saida = db.Column(db.Integer, default=0)
    sefaz_nfe_entrada = db.Column(db.Integer, default=0)
    sefaz_cte_emitido = db.Column(db.Integer, default=0)
    sefaz_cte_tomado = db.Column(db.Integer, default=0)
    sefaz_nfce = db.Column(db.Integer, default=0)
    active = db.Column(db.Integer, default=0)
    active_mensal = db.Column(db.Integer, default=0)
    finished_mensal = db.Column(db.Integer, default=0)
    notes = db.Column(db.String(120))
    # RELAÇÕES
    city = db.relationship('City')
    empresa = db.relationship('Empresas')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class PessoaFisica(db.Model):
    __tablename__ = 'PessoaFisica'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    id_empresa = db.Column(db.Integer, db.ForeignKey('Empresas.id'))
    name = db.Column(db.String(80))
    cnpj_cpf = db.Column(db.String(11))
    ie = db.Column(db.Integer)
    id_city = db.Column(db.Integer, db.ForeignKey('City.id'))
    password = db.Column(db.String(64))
    pref_enc_tomado = db.Column(db.Integer, default=0)
    pref_enc_prestado = db.Column(db.Integer, default=0)
    pref_guia_issqn = db.Column(db.Integer, default=0)
    pref_rel_tomado = db.Column(db.Integer, default=0)
    pref_rel_prestado = db.Column(db.Integer, default=0)
    pref_nfe_tomado = db.Column(db.Integer, default=0)
    pref_nfe_prestado = db.Column(db.Integer, default=0)
    sefaz_nfe_saida = db.Column(db.Integer, default=0)
    sefaz_nfe_entrada = db.Column(db.Integer, default=0)
    sefaz_cte_emitido = db.Column(db.Integer, default=0)
    sefaz_cte_tomado = db.Column(db.Integer, default=0)
    sefaz_nfce = db.Column(db.Integer, default=0)
    active = db.Column(db.Integer, default=0)
    active_mensal = db.Column(db.Integer, default=0)
    finished_mensal = db.Column(db.Integer, default=0)
    notes = db.Column(db.String(120))
    # RELAÇÕES
    city = db.relationship('City')
    empresa = db.relationship('Empresas')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class City(db.Model):
    __tablename__ = 'City'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    name = db.Column(db.String(64))
    uf = db.Column(db.String(2), db.ForeignKey('UF.uf'))
    name_uf = db.Column(db.String(64))
    active = db.Column(db.Integer)
    active_prefeituras = db.Column(db.Integer)
    uf_uf = db.relationship('UF')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class UF(db.Model):
    __tablename__ = 'UF'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    uf = db.Column(db.String(2))
    cod_uf = db.Column(db.Integer)
    uf_desc = db.Column(db.String(64))
    active_sefaz = db.Column(db.Integer)

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class FilesParameters(db.Model):
    __tablename__ = 'FilesParameters'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    parameter = db.Column(db.String(64))
    variable = db.Column(db.String(200))
    desc = db.Column(db.String(200))

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class ThreadingCounter(db.Model):
    __tablename__ = 'ThreadingCounter'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    thread_name = db.Column(db.String(120))
    orgao_exec = db.Column(db.String(64))
    tipo_exec = db.Column(db.String(64))
    user_exec = db.Column(db.String(64), db.ForeignKey('Users.username'))
    id_empresa = db.Column(db.Integer, db.ForeignKey('Empresas.id'))
    percentil = db.Column(db.Integer, default=0)
    nome_arquivo = db.Column(db.String(64))
    data_exec = db.Column(db.DateTime())
    thread_finished = db.Column(db.Integer, default=0)
    # RELACOES
    empresa = db.relationship('Empresas')
    usuario = db.relationship('Users')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class logData(db.Model):
    __tablename__ = 'logData'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    thread_name = db.Column(db.String(120), db.ForeignKey('ThreadingCounter.thread_name'))
    log_title = db.Column(db.String(64))
    log_desc = db.Column(db.String(64))
    cnpj_cpf = db.Column(db.String(64))
    data = db.Column(db.DateTime())
    tipo = db.Column(db.String(64))
    bg_tipo = db.Column(db.String(64))
    status = db.Column(db.String(64))
    bg_status = db.Column(db.String(64))
    # RELACOES
    thread = db.relationship('ThreadingCounter')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)


class AgendamentosRPA(db.Model):
    __tablename__ = 'AgendamentosRPA'

    id = db.Column(db.Integer, primary_key=True, unique=True)
    data_cadastro = db.Column(db.DateTime())
    id_empresa = db.Column(db.Integer, db.ForeignKey('Empresas.id'))
    user_agendamento = db.Column(db.String(64), db.ForeignKey('Users.username'))
    tipo_agendamento = db.Column(db.String(64))
    cd_ufcidade_agendamento = db.Column(db.String(64))
    data_primeiro_agendamento = db.Column(db.DateTime())
    processos_inclusos = db.Column(db.String(400))
    tipo_pessoa_agendamento = db.Column(db.String(12))
    in_repeat = db.Column(db.Integer)
    in_comp_atual = db.Column(db.Integer)
    status = db.Column(db.String(64))
    status_sender = db.Column(db.String(200))
    job_trigger = db.Column(db.String(64))
    job_data = db.Column(db.String(200))
    active = db.Column(db.Integer)
    path_receiver = db.Column(db.String(200))
    # RELACOES
    empresa = db.relationship('Empresas')
    usuario = db.relationship('Users')

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]

            setattr(self, property, value)
