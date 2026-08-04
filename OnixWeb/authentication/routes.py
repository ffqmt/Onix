# -*- encoding: utf-8 -*-
from collections import defaultdict
from datetime import datetime

from flask import render_template, redirect, request, url_for, flash
from jinja2 import TemplateNotFound
from flask_login import (
    current_user,
    login_user,
    logout_user
)
from sqlalchemy import inspect

from OnixWeb.addons.util import verify_pass, get_segment, log_message
from OnixWeb import db, login_manager
from OnixWeb.authentication import blueprint
from OnixWeb.addons.models import Users, Empresas


@blueprint.app_context_processor
def processorDadosUsuario():
    def EmpresaUsuario():
        try:
            usuario = Users.query.filter_by(username=current_user.username).first()
            empresa = Empresas.query.filter_by(cnpj=usuario.cnpj_empresa).first()
        except Exception as e:
            print(f"#ERRO -> processorDadosUsuario - EmpresaUsuario: {e}")
            empresa = []
        return empresa

    return dict(EmpresaUsuario=EmpresaUsuario)


@blueprint.route('/')
def route_default():
    return redirect(url_for('authentication_blueprint.index'))


@blueprint.route('/index')
def index():
    if current_user.is_authenticated:
        segment = get_segment(request)
        return render_template('html/index.html', segment=segment)
    else:
        segment = get_segment(request)
        return render_template('html/index.html', segment=segment)


@blueprint.route('/<template>')
# @login_required
def route_template(template):
    try:
        if not template.endswith('.html'):
            template += '.html'
        segment = get_segment(request)
        log_message()
        return render_template(f"html/" + template, segment=segment)

    except TemplateNotFound:
        log_message()
        return render_template('errors/page-404.html'), 404

    except ():
        log_message()
        return render_template('errors/page-500.html'), 500


@blueprint.route('/login', methods=['GET', 'POST'])
def login():
    segment = get_segment(request)
    if request.method == 'GET':
        if not current_user.is_authenticated:
            return render_template('accounts/login.html',
                                   segment=segment)
    if request.method == 'POST':
        if 'validateCnpj' in request.form:
            cnpjOnly = request.form.get('cnpj').replace('.', '').replace('/', '').replace('-', '')
            chave_acesso = request.form.get('chave_acesso')
            if len(cnpjOnly) < 14:
                flash([f"O CNPJ informado possui menos que 14 digitos.", "OK", "", "mensagem"],
                      [f"CNPJ Inválido", "error"],
                      )
            else:
                empresa = Empresas.query.filter_by(cnpj=cnpjOnly).first()
                if empresa:
                    if empresa.chave_acesso == chave_acesso:
                        if not empresa or empresa.licensed_until <= datetime.now():
                            flash([f"O CNPJ informado não possui licença válida.", "OK", "", "mensagem"],
                                  [f"Licença não Encontrada", "warning"],
                                  )
                        elif empresa and empresa.licensed_until >= datetime.now():
                            return render_template('accounts/login_user.html',
                                                   Empresa=empresa,
                                                   segment=segment)
                    else:
                        flash([f"A Chave de acesso ou CNPJ são inválidos.", "OK", "", "mensagem"],
                              [f"Dados Inválidos", "warning"],
                              )
                else:
                    flash([f"A Chave de acesso ou CNPJ são inválidos.", "OK", "", "mensagem"],
                          [f"Dados Inválidos", "warning"],
                          )

        if 'validateUser' in request.form:
            cnpj = request.form.get('empresa')
            username = request.form.get('usuario')
            password = request.form.get('senha')
            empresa = Empresas.query.filter_by(cnpj=cnpj).first()
            user = Users.query.filter_by(username=username.upper()).first()

            if user and verify_pass(password, user.password) and user.id_empresa == empresa.id:
                login_user(user)
                return redirect(url_for('authentication_blueprint.route_default'))

            logout_user()  # PRECISA TER O LOGOUT, SE NAO BUGA O LOGIN
            flash([f"Por favor, verifique os dados informados!", "OK", "", "mensagem"],
                  [f"Impossível Entrar", "error"],
                  )
            return render_template('accounts/login_user.html',
                                   Empresa=empresa,
                                   segment=segment)

        if not current_user.is_authenticated:
            return render_template('accounts/login.html',
                                   segment='login')

    return redirect(url_for('authentication_blueprint.route_default'))


@blueprint.route('/!@#&!(#!@#!@#!', methods=['GET', 'POST'])
def register():
    segment = get_segment(request)
    if 'register' in request.form:

        username = request.form.get('username')

        user = Users.query.filter_by(username=username).first()
        if user:
            return render_template('accounts/register.html',
                                   msg='Usuário já registrado!',
                                   success=False,
                                   segment=segment
                                   )

        user = Users(**request.form)
        db.session.add(user)
        db.session.commit()
        # logout_user()

        return render_template('accounts/register.html',
                               msg='Usuário criado com sucesso...',
                               success=True,
                               segment=segment
                               )

    else:
        return render_template('accounts/register.html', segment=segment)


@blueprint.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('authentication_blueprint.login'))


# Errors

@login_manager.unauthorized_handler
def unauthorized_handler():
    return render_template('errors/page-403.html'), 403


@blueprint.errorhandler(403)
def access_forbidden(error):
    return render_template('errors/page-403.html'), 403


@blueprint.errorhandler(404)
def not_found_error(error):
    return render_template('errors/page-404.html'), 404


@blueprint.errorhandler(500)
def internal_error(error):
    return render_template('errors/page-500.html'), 500
