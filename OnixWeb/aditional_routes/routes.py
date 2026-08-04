# -*- encoding: utf-8 -*-
import os
import hashlib
import threading
from datetime import datetime
from time import sleep

import pytz
from flask import render_template, redirect, request, url_for, flash, make_response, send_file, jsonify
from jinja2 import TemplateNotFound
from flask_login import (
    current_user,
    login_user,
    logout_user, login_required
)
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from OnixWeb import db, login_manager, csrf
from OnixWeb.addons.agendamentos import scheduler, agendamentoAddSchenduler
from OnixWeb.addons.util import get_segment, log_message
from OnixWeb.aditional_routes import blueprint
from OnixWeb.addons.models import Users, Empresas, PessoaJuridica, City, PessoaFisica, ThreadingCounter, logData, UF, \
    AgendamentosRPA
from OnixWeb.rpautomation.prefeituras import MT_1
from OnixWeb.rpautomation.sefaz import MT

basedir = os.path.abspath('')
root_path = os.path.abspath('')

CUSTOM_DB_PATH = None
CUSTOM_ROOT_PATH = None

def get_root_path():
    global CUSTOM_ROOT_PATH
    if CUSTOM_ROOT_PATH:
        return CUSTOM_ROOT_PATH
    return root_path


def checkOnOff(x):
    if x == 'on':
        return True
    else:
        return False


@blueprint.app_context_processor
def processorDadosAdicionais():
    def agora():
        agora = datetime.now()
        fuso_horario = pytz.timezone("America/Cuiaba")
        agora = fuso_horario.localize(agora)
        return agora

    def listCity():
        city = []
        CT = City.query.filter_by(active=1).all()
        for c in CT:
            city.append(
                {
                    "id": c.id,
                    "name": c.name_uf
                }
            )
        return city

    def CityTable():
        city = City.query.filter_by(active=1).all()
        return city

    def UFTable():
        uf = UF.query.all()
        return uf

    def EmpresasCidadePrefeituras(id_cidade):
        empresas = (PessoaJuridica.query
                    .filter_by(id_city=id_cidade, id_empresa=current_user.empresa.id, active=True)
                    .filter(PessoaJuridica.password != '')
                    .filter(or_(PessoaJuridica.pref_enc_tomado == True,
                                PessoaJuridica.pref_enc_prestado == True,
                                PessoaJuridica.pref_guia_issqn == True,
                                PessoaJuridica.pref_rel_tomado == True,
                                PessoaJuridica.pref_rel_prestado == True,
                                PessoaJuridica.pref_nfe_tomado == True,
                                PessoaJuridica.pref_nfe_prestado == True))
                    .all())
        return empresas

    def FisicasCidadePrefeituras(id_cidade):
        fisicas = (PessoaFisica.query
                   .filter_by(id_city=id_cidade, id_empresa=current_user.empresa.id, active=True)
                   .filter(PessoaFisica.password != '')
                   .filter(or_(PessoaFisica.pref_enc_tomado == True,
                               PessoaFisica.pref_enc_prestado == True,
                               PessoaFisica.pref_guia_issqn == True,
                               PessoaFisica.pref_rel_tomado == True,
                               PessoaFisica.pref_rel_prestado == True,
                               PessoaFisica.pref_nfe_tomado == True,
                               PessoaFisica.pref_nfe_prestado == True))
                   .all())
        return fisicas

    def EmpresasEstadoSefaz(id_uf):
        uf = UF.query.filter_by(id=id_uf).first()
        empresas = (PessoaJuridica.query
                    .join(City)
                    .options(joinedload(PessoaJuridica.city))
                    .filter(PessoaJuridica.id_empresa == current_user.empresa.id,
                            PessoaJuridica.active == True)
                    .filter(City.uf == uf.uf)
                    .filter(or_(PessoaJuridica.sefaz_nfe_saida == True,
                                PessoaJuridica.sefaz_nfe_entrada == True,
                                PessoaJuridica.sefaz_cte_emitido == True,
                                PessoaJuridica.sefaz_cte_tomado == True,
                                PessoaJuridica.sefaz_nfce == True))
                    .all())
        return empresas

    def FisicasEstadoSefaz(id_uf):
        uf = UF.query.filter_by(id=id_uf).first()
        fisicas = (PessoaFisica.query
                   .join(City)
                   .options(joinedload(PessoaFisica.city))
                   .filter(PessoaFisica.id_empresa == current_user.empresa.id,
                           PessoaFisica.active == True)
                   .filter(City.uf == uf.uf)
                   .filter(or_(PessoaFisica.sefaz_nfe_saida == True,
                               PessoaFisica.sefaz_nfe_entrada == True,
                               PessoaFisica.sefaz_cte_emitido == True,
                               PessoaFisica.sefaz_cte_tomado == True,
                               PessoaFisica.sefaz_nfce == True))
                   .all())
        print(fisicas)
        return fisicas

    def dadosAgendamento(id_agendamento):
        agendamento = AgendamentosRPA.query.filter_by(id=id_agendamento).first()
        return agendamento

    def getJob(id_agendamento):
        try:
            job = scheduler.get_job(f'{id_agendamento}')
        except Exception:
            job = []
        return job

    return dict(listCity=listCity,
                CityTable=CityTable,
                EmpresasCidadePrefeituras=EmpresasCidadePrefeituras,
                FisicasCidadePrefeituras=FisicasCidadePrefeituras,
                UFTable=UFTable,
                EmpresasEstadoSefaz=EmpresasEstadoSefaz,
                FisicasEstadoSefaz=FisicasEstadoSefaz,
                dadosAgendamento=dadosAgendamento,
                getJob=getJob,
                agora=agora)


@blueprint.route('/param-cad-pessoajuridica', methods=['GET', 'POST'])
@login_required
def param_cad_pessoajuridica():
    segment = get_segment(request)
    if request.method == 'GET':
        ''
    elif request.method == 'POST' and 'salvarAlteracoes' in request.form:
        try:
            checagemCNPJ = (PessoaJuridica.query
                            .filter_by(
                cnpj_cpf=request.form.get('cnpj_cpf').replace('.', '').replace('/', '').replace('-', ''))
                            .filter(PessoaJuridica.id != request.form.get('id'))
                            .first())
            checagemIE = (PessoaJuridica.query
                          .filter(PessoaJuridica.ie != '')
                          .filter_by(ie=request.form.get('ie'))
                          .filter(PessoaJuridica.id != request.form.get('id'))
                          .first())
            if checagemIE:
                raise Exception('IE#Duplicated')
            if checagemCNPJ:
                raise Exception('CNPJ#Duplicated')

            cadastro = PessoaJuridica.query.filter_by(id=request.form.get('id'),
                                                      id_empresa=current_user.empresa.id).first()
            cadastro.id_empresa = current_user.empresa.id
            cadastro.name = request.form.get('name')
            cadastro.cnpj_cpf = request.form.get('cnpj_cpf').replace('.', '').replace('/', '').replace('-', '')
            cadastro.ie = request.form.get('ie')
            cadastro.password = request.form.get('password')
            cadastro.id_city = int(request.form.get('city'))

            cadastro.pref_enc_tomado = checkOnOff(request.form.get('pref_enc_tomado'))
            cadastro.pref_enc_prestado = checkOnOff(request.form.get('pref_enc_prestado'))
            cadastro.pref_guia_issqn = checkOnOff(request.form.get('pref_guia_issqn'))
            cadastro.pref_rel_tomado = checkOnOff(request.form.get('pref_rel_tomado'))
            cadastro.pref_rel_prestado = checkOnOff(request.form.get('pref_rel_prestado'))
            cadastro.pref_nfe_tomado = checkOnOff(request.form.get('pref_nfe_tomado'))
            cadastro.pref_nfe_prestado = checkOnOff(request.form.get('pref_nfe_prestado'))
            cadastro.sefaz_nfe_saida = checkOnOff(request.form.get('sefaz_nfe_saida'))
            cadastro.sefaz_nfe_entrada = checkOnOff(request.form.get('sefaz_nfe_entrada'))
            cadastro.sefaz_cte_emitido = checkOnOff(request.form.get('sefaz_cte_emitido'))
            cadastro.sefaz_cte_tomado = checkOnOff(request.form.get('sefaz_cte_tomado'))
            cadastro.sefaz_nfce = checkOnOff(request.form.get('sefaz_nfce'))
            cadastro.active = checkOnOff(request.form.get('active'))
            cadastro.active_mensal = checkOnOff(request.form.get('active_mensal'))

            db.session.commit()
            flash([f"Alterações salvas com sucesso!", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        except Exception as e:
            db.session.rollback()
            if 'CNPJ#Duplicated' in str(e):
                flash([f"Já existe um cadastro com esse CNPJ.", "OK", "", "mensagem"],
                      [f"Cadastro Duplicado", "error"],
                      )
            elif 'IE#Duplicated' in str(e):
                flash([f"Já existe um cadastro com essa IE.", "OK", "", "mensagem"],
                      [f"Cadastro Duplicado", "error"],
                      )
            else:
                flash([f"Erro ao salvar informações no banco de dados.", "OK", "", "mensagem"],
                      [f"Erro de BD", "error"],
                      )

    elif request.method == 'POST' and 'addCadastro' in request.form:
        try:
            checagemCNPJ = (PessoaJuridica.query
                            .filter(PessoaJuridica.id_empresa == current_user.empresa.id)
                            .filter_by(
                cnpj_cpf=request.form.get('cnpj_cpf').replace('.', '').replace('/', '').replace('-', ''))
                            .first())
            checagemIE = (PessoaJuridica.query
                          .filter(PessoaJuridica.id_empresa == current_user.empresa.id)
                          .filter(PessoaJuridica.ie != '')
                          .filter_by(ie=request.form.get('ie'))
                          .first())
            if checagemIE:
                raise Exception('IE#Duplicated')
            if checagemCNPJ:
                raise Exception('CNPJ#Duplicated')
            NewCad = PessoaJuridica()
            NewCad.id_empresa = current_user.empresa.id
            NewCad.name = request.form.get('name')
            NewCad.cnpj_cpf = request.form.get('cnpj_cpf').replace('.', '').replace('/', '').replace('-', '')
            NewCad.ie = request.form.get('ie')
            NewCad.password = request.form.get('password')
            NewCad.id_city = int(request.form.get('city'))

            NewCad.pref_enc_tomado = checkOnOff(request.form.get('pref_enc_tomado'))
            NewCad.pref_enc_prestado = checkOnOff(request.form.get('pref_enc_prestado'))
            NewCad.pref_guia_issqn = checkOnOff(request.form.get('pref_guia_issqn'))
            NewCad.pref_rel_tomado = checkOnOff(request.form.get('pref_rel_tomado'))
            NewCad.pref_rel_prestado = checkOnOff(request.form.get('pref_rel_prestado'))
            NewCad.pref_nfe_tomado = checkOnOff(request.form.get('pref_nfe_tomado'))
            NewCad.pref_nfe_prestado = checkOnOff(request.form.get('pref_nfe_prestado'))
            NewCad.sefaz_nfe_saida = checkOnOff(request.form.get('sefaz_nfe_saida'))
            NewCad.sefaz_nfe_entrada = checkOnOff(request.form.get('sefaz_nfe_entrada'))
            NewCad.sefaz_cte_emitido = checkOnOff(request.form.get('sefaz_cte_emitido'))
            NewCad.sefaz_cte_tomado = checkOnOff(request.form.get('sefaz_cte_tomado'))
            NewCad.sefaz_nfce = checkOnOff(request.form.get('sefaz_nfce'))
            NewCad.active = checkOnOff(request.form.get('active'))
            NewCad.active_mensal = checkOnOff(request.form.get('active_mensal'))

            db.session.add(NewCad)
            db.session.commit()
            flash([f"Cadastro adicionado com sucesso!", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        except Exception as e:
            print(e)
            db.session.rollback()
            if 'CNPJ#Duplicated' in str(e):
                flash([f"Já existe um cadastro com esse CNPJ.", "OK", "", "mensagem"],
                      [f"Cadastro Duplicado", "error"],
                      )
            elif 'IE#Duplicated' in str(e):
                flash([f"Já existe um cadastro com essa IE.", "OK", "", "mensagem"],
                      [f"Cadastro Duplicado", "error"],
                      )
            else:
                flash([f"Erro ao salvar informações no banco de dados.", "OK", "", "mensagem"],
                      [f"Erro de BD", "error"],
                      )

    elif request.method == 'POST' and 'deletarCadastro' in request.form:
        try:
            delCad = PessoaJuridica.query.filter_by(id=request.form.get('deletarCadastro'),
                                                    id_empresa=current_user.empresa.id).first()
            db.session.delete(delCad)
            db.session.commit()
            flash([f"Cadastro deletado com sucesso!", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        except Exception as e:
            print(e)
            db.session.rollback()
            flash([f"Erro ao salvar informações no banco de dados.", "OK", "", "mensagem"],
                  [f"Erro de BD", "error"],
                  )

    JuridicaRDA = (PessoaJuridica.query
                   .filter_by(id_empresa=current_user.empresa.id)
                   .all())
    return render_template('sistemas/RPAS/parametrizacoes/cadastros/pessoajuridica.html',
                           segment=segment,
                           JuridicaRDA=JuridicaRDA)


@blueprint.route('/fetchEditJuridica', methods=['POST'])
@login_required
def fetchEditJuridica():
    response = make_response()
    segment = get_segment(request)
    dados = request.get_json()
    edit = PessoaJuridica.query.filter_by(id=dados[0], id_empresa=current_user.empresa.id).first()
    response.data = render_template('sistemas/RPAS/parametrizacoes/cadastros/modals/modal_rda_edit.html',
                                    segment=segment,
                                    cadEdit=edit)
    response.headers['style'] = 'notice1'
    response.headers['title'] = 'Alterando Empresa!'
    response.headers['message'] = f'empresa {edit.name} esta sendo alterada!'
    return response


@blueprint.route('/fetchDelJuridica', methods=['POST'])
@login_required
def fetchDelJuridica():
    response = make_response()
    segment = get_segment(request)
    dados = request.get_json()
    delet = PessoaJuridica.query.filter_by(id=dados[0], id_empresa=current_user.empresa.id).first()
    response.data = render_template('sistemas/RPAS/parametrizacoes/cadastros/modals/modal_rda_del.html',
                                    segment=segment,
                                    cadDel=delet)
    response.headers['style'] = 'warning1'
    response.headers['title'] = 'Deletando Empresa!'
    response.headers['message'] = f'empresa {delet.name} esta sendo deletada!'
    return response


@blueprint.route('/param-cad-pessoafisica', methods=['GET', 'POST'])
@login_required
def param_cad_pessoafisica():
    segment = get_segment(request)
    if request.method == 'GET':
        ''
    elif request.method == 'POST' and 'salvarAlteracoes' in request.form:
        try:
            checagemIE = (PessoaFisica.query
                          .filter(PessoaFisica.id_empresa == current_user.empresa.id)
                          .filter(PessoaFisica.ie != '')
                          .filter_by(ie=request.form.get('ie'))
                          .filter(PessoaFisica.id != request.form.get('id'))
                          .first())
            if checagemIE:
                raise Exception('IE#Duplicated')

            cadastro = PessoaFisica.query.filter_by(id=request.form.get('id'),
                                                    id_empresa=current_user.empresa.id).first()
            cadastro.id_empresa = current_user.empresa.id
            cadastro.name = request.form.get('name')
            cadastro.cnpj_cpf = request.form.get('cnpj_cpf').replace('.', '').replace('/', '').replace('-', '')
            cadastro.ie = request.form.get('ie')
            cadastro.password = request.form.get('password')
            cadastro.id_city = int(request.form.get('city'))

            cadastro.pref_enc_tomado = checkOnOff(request.form.get('pref_enc_tomado'))
            cadastro.pref_enc_prestado = checkOnOff(request.form.get('pref_enc_prestado'))
            cadastro.pref_guia_issqn = checkOnOff(request.form.get('pref_guia_issqn'))
            cadastro.pref_rel_tomado = checkOnOff(request.form.get('pref_rel_tomado'))
            cadastro.pref_rel_prestado = checkOnOff(request.form.get('pref_rel_prestado'))
            cadastro.pref_nfe_tomado = checkOnOff(request.form.get('pref_nfe_tomado'))
            cadastro.pref_nfe_prestado = checkOnOff(request.form.get('pref_nfe_prestado'))
            cadastro.sefaz_nfe_saida = checkOnOff(request.form.get('sefaz_nfe_saida'))
            cadastro.sefaz_nfe_entrada = checkOnOff(request.form.get('sefaz_nfe_entrada'))
            cadastro.sefaz_cte_emitido = checkOnOff(request.form.get('sefaz_cte_emitido'))
            cadastro.sefaz_cte_tomado = checkOnOff(request.form.get('sefaz_cte_tomado'))
            cadastro.sefaz_nfce = checkOnOff(request.form.get('sefaz_nfce'))
            cadastro.active = checkOnOff(request.form.get('active'))
            cadastro.active_mensal = checkOnOff(request.form.get('active_mensal'))

            db.session.commit()
            flash([f"Alterações salvas com sucesso!", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        except Exception as e:
            db.session.rollback()
            if 'IE#Duplicated' in str(e):
                flash([f"Já existe um cadastro com essa IE.", "OK", "", "mensagem"],
                      [f"Cadastro Duplicado", "error"],
                      )
            else:
                flash([f"Erro ao salvar informações no banco de dados.", "OK", "", "mensagem"],
                      [f"Erro de BD", "error"],
                      )

    elif request.method == 'POST' and 'addCadastro' in request.form:
        try:
            checagemIE = (PessoaFisica.query
                          .filter(PessoaFisica.id_empresa == current_user.empresa.id)
                          .filter(PessoaFisica.ie != '')
                          .filter_by(ie=request.form.get('ie'))
                          .first())
            if checagemIE:
                raise Exception('IE#Duplicated')

            NewCad = PessoaFisica()
            NewCad.id_empresa = current_user.empresa.id
            NewCad.name = request.form.get('name')
            NewCad.cnpj_cpf = request.form.get('cnpj_cpf').replace('.', '').replace('/', '').replace('-', '')
            NewCad.ie = request.form.get('ie')
            NewCad.password = request.form.get('password')
            NewCad.id_city = int(request.form.get('city'))

            NewCad.pref_enc_tomado = checkOnOff(request.form.get('pref_enc_tomado'))
            NewCad.pref_enc_prestado = checkOnOff(request.form.get('pref_enc_prestado'))
            NewCad.pref_guia_issqn = checkOnOff(request.form.get('pref_guia_issqn'))
            NewCad.pref_rel_tomado = checkOnOff(request.form.get('pref_rel_tomado'))
            NewCad.pref_rel_prestado = checkOnOff(request.form.get('pref_rel_prestado'))
            NewCad.pref_nfe_tomado = checkOnOff(request.form.get('pref_nfe_tomado'))
            NewCad.pref_nfe_prestado = checkOnOff(request.form.get('pref_nfe_prestado'))
            NewCad.sefaz_nfe_saida = checkOnOff(request.form.get('sefaz_nfe_saida'))
            NewCad.sefaz_nfe_entrada = checkOnOff(request.form.get('sefaz_nfe_entrada'))
            NewCad.sefaz_cte_emitido = checkOnOff(request.form.get('sefaz_cte_emitido'))
            NewCad.sefaz_cte_tomado = checkOnOff(request.form.get('sefaz_cte_tomado'))
            NewCad.sefaz_nfce = checkOnOff(request.form.get('sefaz_nfce'))
            NewCad.active = checkOnOff(request.form.get('active'))
            NewCad.active_mensal = checkOnOff(request.form.get('active_mensal'))

            db.session.add(NewCad)
            db.session.commit()
            flash([f"Cadastro adicionado com sucesso!", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        except Exception as e:
            print(e)
            db.session.rollback()
            if 'IE#Duplicated' in str(e):
                flash([f"Já existe um cadastro com essa IE.", "OK", "", "mensagem"],
                      [f"Cadastro Duplicado", "error"],
                      )
            else:
                flash([f"Erro ao salvar informações no banco de dados.", "OK", "", "mensagem"],
                      [f"Erro de BD", "error"],
                      )

    elif request.method == 'POST' and 'deletarCadastro' in request.form:
        try:
            delCad = PessoaFisica.query.filter_by(id=request.form.get('deletarCadastro'),
                                                  id_empresa=current_user.empresa.id).first()
            db.session.delete(delCad)
            db.session.commit()
            flash([f"Cadastro deletado com sucesso!", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        except Exception as e:
            print(e)
            db.session.rollback()
            flash([f"Erro ao salvar informações no banco de dados.", "OK", "", "mensagem"],
                  [f"Erro de BD", "error"],
                  )

    FisicaRDA = (PessoaFisica.query
                 .filter_by(id_empresa=current_user.empresa.id)
                 .all())
    return render_template('sistemas/RPAS/parametrizacoes/cadastros/pessoafisica.html',
                           segment=segment,
                           FisicaRDA=FisicaRDA)


@blueprint.route('/fetchEditFisica', methods=['POST'])
@login_required
def fetchEditFisica():
    response = make_response()
    segment = get_segment(request)
    dados = request.get_json()
    edit = PessoaFisica.query.filter_by(id=dados[0], id_empresa=current_user.empresa.id).first()
    response.data = render_template('sistemas/RPAS/parametrizacoes/cadastros/modals/modal_rda_edit.html',
                                    segment=segment,
                                    cadEdit=edit)
    response.headers['style'] = 'notice1'
    response.headers['title'] = 'Alterando Pessoa Física!'
    response.headers['message'] = f'Pessoa fisica {edit.name} esta sendo alterada!'
    return response


@blueprint.route('/fetchDelFisica', methods=['POST'])
@login_required
def fetchDelFisica():
    response = make_response()
    segment = get_segment(request)
    dados = request.get_json()
    delet = PessoaFisica.query.filter_by(id=dados[0], id_empresa=current_user.empresa.id).first()
    response.data = render_template('sistemas/RPAS/parametrizacoes/cadastros/modals/modal_rda_del.html',
                                    segment=segment,
                                    cadDel=delet)
    response.headers['style'] = 'warning1'
    response.headers['title'] = 'Deletando Pessoa Física!'
    response.headers['message'] = f'Pessoa física {delet.name} esta sendo deletada!'
    return response


@blueprint.route('/param-cad-acessos', methods=['GET', 'POST'])
@login_required
def param_cad_acessos():
    segment = get_segment(request)
    Empresa = Empresas.query.filter_by(id=current_user.empresa.id).first()
    if request.method == 'GET':
        ''
    if request.method == 'POST' and 'altPasswordEmpresa' in request.form:
        if request.form.get('newPassEmp1') == request.form.get('newPassEmp2'):
            Empresa.chave_acesso = request.form.get('newPassEmp1')
            db.session.commit()
            flash([f"Alteração Realizada.", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        else:
            flash([f"Alteração não realizada, verifique se as duas senhas são iguais.", "OK", "", "mensagem"],
                  [f"Atenção", "warning"],
                  )
    elif request.method == 'POST' and 'altPasswordContabilista' in request.form:
        if request.form.get('newPassContabilista1') == request.form.get('newPassContabilista2'):
            Empresa.senha_contabilista = request.form.get('newPassContabilista1')
            db.session.commit()
            flash([f"Alteração Realizada.", "OK", "", "mensagem"],
                  [f"Sucesso", "success"],
                  )
        else:
            flash([f"Alteração não realizada, verifique se as duas senhas são iguais.", "OK", "", "mensagem"],
                  [f"Atenção", "warning"],
                  )

    return render_template('sistemas/RPAS/parametrizacoes/cadastros/acessos.html',
                           segment=segment,
                           Empresa=Empresa)


@blueprint.route('/autom-rpas-prefeituras-<estado>-<id_cidade>', methods=['GET', 'POST'])
@login_required
def autom_rpas_prefeituras(estado, id_cidade):
    segment = get_segment(request)
    cidade = City.query.filter(City.id == id_cidade, City.uf == estado).first()
    paramTipoPessoa = ''
    SemParametros = False
    if request.method == 'GET':
        ''
    elif request.method == 'POST' and ('PessoaJuridica' in request.form or 'PessoaFisica' in request.form):
        if 'PessoaJuridica' in request.form:
            paramTipoPessoa = 'Juridica'
        if 'PessoaFisica' in request.form:
            paramTipoPessoa = 'Fisica'
    elif request.method == 'POST' and 'execPrefeituras' in request.form:
        competenciaMes = int(request.form.get('competencia').split('-')[0])
        competenciaAno = int(request.form.get('competencia').split('-')[1])
        codigo_unico = hashlib.sha256(os.urandom(16)).hexdigest()
        newThreadLogid = ThreadingCounter()
        newThreadLogid.thread_name = f"{codigo_unico}"
        newThreadLogid.orgao_exec = 'PREFEITURA'
        newThreadLogid.tipo_exec = 'AUTOMACAO'
        newThreadLogid.user_exec = current_user.username
        newThreadLogid.id_empresa = current_user.empresa.id
        newThreadLogid.data_exec = datetime.now()
        newThreadLogid.nome_arquivo = current_user.empresa.nome.split()[0].upper()

        threadDataLog = logData()
        threadDataLog.thread_name = f"{codigo_unico}"
        threadDataLog.log_title = 'Iniciando...'
        threadDataLog.log_desc = 'RPA iniciado.'
        threadDataLog.cnpj_cpf = 'BOT'
        threadDataLog.data = datetime.now()
        threadDataLog.tipo = 'BOT'
        threadDataLog.bg_tipo = 'primary-gradient'
        threadDataLog.status = 'SUCESSO'
        threadDataLog.bg_status = 'success-gradient'

        db.session.add(newThreadLogid)
        db.session.add(threadDataLog)
        db.session.commit()

        tipo_pessoa = request.form.get('tipo_pessoa')
        tipo = request.form.get('tipo')
        listaPessoas = list(request.form.get('selecao').split(','))
        if tipo == 'padrao':  # PADRAO
            if tipo_pessoa == 'Fisica':
                callExec = getattr(globals()[estado + '_' + id_cidade], 'MainExecution_Fisica_Padrao', None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )

            elif tipo_pessoa == 'Juridica':
                callExec = getattr(globals()[estado + '_' + id_cidade], 'MainExecution_Juridica_Padrao',
                                   None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )
            else:
                flash(
                    [f"Automação não iniciada, automação para a cidade não encontrada.", "OK", "", "mensagem"],
                    [f"Atenção", "error"],
                )

            return redirect(url_for('aditional_blueprint.fetchlog', logname=codigo_unico))
        elif tipo == 'expecifico':  # EXPECIFICO
            listaParametros = {
                'enc_taken': checkOnOff(request.form.get('enc_taken')),
                'enc_provided': checkOnOff(request.form.get('enc_provided')),
                'issqn': checkOnOff(request.form.get('issqn')),
                'taken': checkOnOff(request.form.get('taken')),
                'provided': checkOnOff(request.form.get('provided')),
                'nfe_taken': checkOnOff(request.form.get('nfe_taken')),
                'nfe_provided': checkOnOff(request.form.get('nfe_provided')),
            }
            if tipo_pessoa == 'Fisica':
                callExec = getattr(globals()[estado + '_' + id_cidade], 'MainExecution_Fisica_Expecifico', None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               listaParametros,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )

            elif tipo_pessoa == 'Juridica':
                callExec = getattr(globals()[estado + '_' + id_cidade], 'MainExecution_Juridica_Expecifico',
                                   None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               listaParametros,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )
            else:
                flash(
                    [f"Automação não iniciada, automação para a cidade não encontrada.", "OK", "", "mensagem"],
                    [f"Atenção", "error"],
                )

            return redirect(url_for('aditional_blueprint.fetchlog', logname=codigo_unico))

    return render_template('sistemas/RPAS/automacoes/prefeituras.html',
                           segment=segment,
                           estado=estado,
                           cidade=cidade,
                           paramTipoPessoa=paramTipoPessoa,
                           SemParametro=SemParametros)


@blueprint.route('fetchlog-<logname>', methods=['GET', 'POST'])
@login_required
def fetchlog(logname):
    segment = get_segment(request)
    response = make_response()
    ThreadFind = ThreadingCounter.query.filter_by(thread_name=logname).first()
    if 'baixarArquivo' in request.form and request.method == 'POST':
        if ThreadFind:
            if ThreadFind.id_empresa == current_user.empresa.id:
                arquivo = f"{ThreadFind.thread_name}" + ".zip"
                nome_arquivo = F'{ThreadFind.nome_arquivo} - {ThreadFind.data_exec.strftime("%d-%m-%Y %H:%M:%S")}' + ".zip"
                caminho_arquivo = f'{get_root_path()}/OnixWeb/rpautomation/transactionFiles/' + arquivo
                response_download = make_response(
                    send_file(caminho_arquivo, download_name=nome_arquivo, as_attachment=True))
                response_download.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                return response_download
            else:
                return render_template('errors/page-404.html'), 404
        else:
            return render_template('errors/page-404.html'), 404
    else:
        if ThreadFind:
            if ThreadFind.id_empresa == current_user.empresa.id:
                if request.method == 'GET':
                    Logs = (logData.query
                            .filter_by(thread_name=logname)
                            .options(joinedload(logData.thread))
                            .all())
                    return render_template('sistemas/RPAS/automacoes/logViewer.html',
                                           segment=segment,
                                           Logs=Logs,
                                           Thread=ThreadFind)
                elif request.method == 'POST':
                    Logs = (logData.query
                            .filter_by(thread_name=logname)
                            .options(joinedload(logData.thread))
                            .all())
                    response.data = render_template('sistemas/RPAS/automacoes/logFetch.html',
                                                    segment=segment,
                                                    Logs=Logs,
                                                    Thread=ThreadFind)
                    return response
            else:
                return render_template('errors/page-404.html'), 404
        else:
            return render_template('errors/page-404.html'), 404


@blueprint.route('/autom-rpas-sefaz-<estado>', methods=['GET', 'POST'])
@login_required
def autom_rpas_sefaz(estado):
    segment = get_segment(request)
    estadoView = UF.query.filter_by(uf=estado, active_sefaz=True).first()
    paramTipoPessoa = ''
    if request.method == 'GET':
        ''
    elif request.method == 'POST' and ('PessoaJuridica' in request.form or 'PessoaFisica' in request.form):
        if 'PessoaJuridica' in request.form:
            paramTipoPessoa = 'Juridica'
        if 'PessoaFisica' in request.form:
            paramTipoPessoa = 'Fisica'
    elif request.method == 'POST' and 'execSefaz' in request.form:
        competenciaMes = int(request.form.get('competencia').split('-')[0])
        competenciaAno = int(request.form.get('competencia').split('-')[1])
        codigo_unico = hashlib.sha256(os.urandom(16)).hexdigest()
        newThreadLogid = ThreadingCounter()
        newThreadLogid.thread_name = f"{codigo_unico}"
        newThreadLogid.orgao_exec = 'SEFAZ'
        newThreadLogid.tipo_exec = 'AUTOMACAO'
        newThreadLogid.user_exec = current_user.username
        newThreadLogid.id_empresa = current_user.empresa.id
        newThreadLogid.data_exec = datetime.now()
        newThreadLogid.nome_arquivo = current_user.empresa.nome.split()[0].upper()

        threadDataLog = logData()
        threadDataLog.id_thread = f"{codigo_unico}"
        threadDataLog.log_title = 'Iniciando...'
        threadDataLog.log_desc = 'RPA iniciado.'
        threadDataLog.cnpj_cpf = 'BOT'
        threadDataLog.data = datetime.now()
        threadDataLog.tipo = 'BOT'
        threadDataLog.bg_tipo = 'primary-gradient'
        threadDataLog.status = 'SUCESSO'
        threadDataLog.bg_status = 'success-gradient'

        db.session.add(newThreadLogid)
        db.session.add(threadDataLog)
        db.session.commit()

        tipo_pessoa = request.form.get('tipo_pessoa')
        tipo = request.form.get('tipo')
        listaPessoas = list(request.form.get('selecao').split(','))
        if tipo == 'padrao':  # PADRAO
            if tipo_pessoa == 'Fisica':
                callExec = getattr(globals()[estado], 'MainExecution_Fisica_Padrao', None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )

            elif tipo_pessoa == 'Juridica':
                callExec = getattr(globals()[estado], 'MainExecution_Juridica_Padrao',
                                   None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )
            else:
                flash(
                    [f"Automação não iniciada, automação para o estado não encontrada.", "OK", "", "mensagem"],
                    [f"Atenção", "error"],
                )
            return redirect(url_for('aditional_blueprint.fetchlog', logname=codigo_unico))
        elif tipo == 'expecifico':  # EXPECIFICO
            listaParametros = {
                'nfe_saida': checkOnOff(request.form.get('nfe_saida')),
                'nfe_entrada': checkOnOff(request.form.get('nfe_entrada')),
                'cte_emissor': checkOnOff(request.form.get('cte_emissor')),
                'cte_tomador': checkOnOff(request.form.get('cte_tomador')),
                'nfce_emitida': checkOnOff(request.form.get('nfce_emitida')),
            }
            if tipo_pessoa == 'Fisica':
                callExec = getattr(globals()[estado], 'MainExecution_Fisica_Expecifico', None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               listaParametros,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )

            elif tipo_pessoa == 'Juridica':
                callExec = getattr(globals()[estado], 'MainExecution_Juridica_Expecifico',
                                   None)
                if callExec is not None and callable(callExec):
                    t = threading.Thread(target=callExec,
                                         name=f"{codigo_unico}",
                                         args=(listaPessoas,
                                               listaParametros,
                                               current_user.id_empresa,
                                               competenciaAno,
                                               competenciaMes))
                    t.start()

                    flash([f"Automação iniciada.", "OK", "", "mensagem"],
                          [f"Sucesso", "success"],
                          )
            else:
                flash(
                    [f"Automação não iniciada, automação para o estado não encontrada.", "OK", "", "mensagem"],
                    [f"Atenção", "error"],
                )
            return redirect(url_for('aditional_blueprint.fetchlog', logname=codigo_unico))

    return render_template('sistemas/RPAS/automacoes/sefaz.html',
                           segment=segment,
                           estado=estadoView,
                           paramTipoPessoa=paramTipoPessoa)


@blueprint.route('/param-cad-agendamentos', methods=['GET', 'POST'])
@login_required
def param_cad_agendamentos():
    segment = get_segment(request)
    if request.method == 'GET':
        ''
    if request.method == 'POST' and 'addAgendamento' in request.form:
        data_agenda = request.form.get('data_agenda')
        data_normalized = datetime.strptime(data_agenda, '%Y-%m-%dT%H:%M:%S')
        data_to_datetime = data_normalized.strftime('%Y-%m-%d %H:%M:%S')
        data_to_datetime = datetime.strptime(data_to_datetime, '%Y-%m-%d %H:%M:%S')
        if data_to_datetime:
            Data_Cadastro = datetime.now()
            Agendamento = AgendamentosRPA()
            Agendamento.id_empresa = current_user.empresa.id
            Agendamento.user_agendamento = current_user.username
            Agendamento.data_cadastro = Data_Cadastro
            Agendamento.tipo_agendamento = request.form.get('tipo_agendamento')
            Agendamento.cd_ufcidade_agendamento = request.form.get('cd_ufcidade_agendamento')
            Agendamento.data_primeiro_agendamento = data_to_datetime
            Agendamento.processos_inclusos = str(request.form.getlist('processos_inclusos')).replace("'", '"')
            Agendamento.tipo_pessoa_agendamento = request.form.get('tipo_pessoa_agendamento')
            Agendamento.in_repeat = checkOnOff(request.form.get('in_repeat'))
            Agendamento.in_comp_atual = checkOnOff(request.form.get('in_comp_atual'))
            Agendamento.status = 'Aguardando Execução'
            Agendamento.active = 1
            Agendamento.path_receiver = request.form.get('path_receiver')

            db.session.add(Agendamento)
            db.session.commit()

            AgendamentoRecemCadastrado = AgendamentosRPA.query.filter_by(data_cadastro=Data_Cadastro,
                                                                         user_agendamento=current_user.username).first()
            agendamentoAddSchenduler(AgendamentoRecemCadastrado.id)

            flash(
                [f"Agendamento cadastrado com sucesso.", "OK", "", "mensagem"],
                [f"Sucesso", "success"],
            )
        else:
            flash(
                [f"O dia e hora informado não pode ser igual a dia e hora atual, agendamento não foi cadastrado.", "OK",
                 "", "mensagem"],
                [f"Atenção", "warning"],
            )
    elif request.method == 'POST' and 'delAgendamento' in request.form:
        Agendamento = AgendamentosRPA.query.filter_by(id=request.form.get('delAgendamento'),
                                                      id_empresa=current_user.empresa.id).first()
        try:
            scheduler.remove_job(f"{Agendamento.id}")
        except Exception:
            'Job removido anteriormente, ignora.'
        db.session.delete(Agendamento)
        db.session.commit()

        flash(
            [f"Agendamento removido com sucesso.", "OK", "", "mensagem"],
            [f"Sucesso", "success"],
        )
    elif request.method == 'POST' and 'altAgeHorario' in request.form:
        Agendamento = AgendamentosRPA.query.filter_by(id=request.form.get('ageid'),
                                                      id_empresa=current_user.empresa.id).first()
        Agendamento.data_primeiro_agendamento = Agendamento.data_primeiro_agendamento.replace(
            hour=int(request.form.get('novohorario')[0:2]), minute=int(request.form.get('novohorario')[3:5]))
        try:
            scheduler.remove_job(f"{Agendamento.id}")
        except Exception:
            'Job removido anteriormente, ignora.'
        db.session.commit()
        try:
            agendamentoAddSchenduler(Agendamento.id)
            flash(
                [f"Horário de Agendamento alterado com sucesso.", "OK", "", "mensagem"],
                [f"Sucesso", "success"],
            )
        except Exception as e:
            print(e)
            flash(
                [f"Horário de Agendamento não alterado.", "OK", "", "mensagem"],
                [f"Atenção", "warning"],
            )



    agendamentosEmpresa = AgendamentosRPA.query.filter_by(id_empresa=current_user.empresa.id).all()
    return render_template('sistemas/RPAS/parametrizacoes/cadastros/agendamentos.html',
                           segment=segment,
                           Agendamentos=agendamentosEmpresa)


@blueprint.route('/scheduled_jobs', methods=['GET', 'POST'])
@login_required
def param_scheduled_jobs():
    SchedulerJobs = scheduler.get_jobs()
    segment = get_segment(request)
    if request.method == 'GET':
        return render_template('admin/scheduled_jobs.html',
                               segment=segment,
                               SchedulerJobs=SchedulerJobs)


@blueprint.route('/fetchEditAgeHo', methods=['POST'])
@login_required
def fetchEditAgeHo():
    response = make_response()
    segment = get_segment(request)
    dados = request.get_json()
    edit = AgendamentosRPA.query.filter_by(id=dados[0], id_empresa=current_user.empresa.id).first()
    response.data = render_template(
        'sistemas/RPAS/parametrizacoes/cadastros/modals/modal_agendamento_alterarhorario.html',
        segment=segment,
        editAgeHour=edit)
    response.headers['style'] = 'notice1'
    response.headers['title'] = 'Alterando Horário!'
    response.headers['message'] = f'O agendamento {edit.id} esta sendo alterado!'
    return response


@blueprint.route('/api/empresas', methods=['GET'])
def api_empresas():
    try:
        from flask_login import current_user

        # Filtra: ativo (active=1) E com pelo menos um processo SEFAZ habilitado
        sefaz_filter = or_(
            PessoaJuridica.sefaz_nfe_saida   == True,
            PessoaJuridica.sefaz_nfe_entrada  == True,
            PessoaJuridica.sefaz_cte_emitido  == True,
            PessoaJuridica.sefaz_cte_tomado   == True,
            PessoaJuridica.sefaz_nfce         == True,
        )
        query_pj = PessoaJuridica.query.filter(
            PessoaJuridica.active == True,
            sefaz_filter
        )
        if current_user and current_user.is_authenticated:
            query_pj = query_pj.filter_by(id_empresa=current_user.empresa.id)
        empresas_pj = query_pj.all()

        sefaz_filter_pf = or_(
            PessoaFisica.sefaz_nfe_saida   == True,
            PessoaFisica.sefaz_nfe_entrada  == True,
            PessoaFisica.sefaz_cte_emitido  == True,
            PessoaFisica.sefaz_cte_tomado   == True,
            PessoaFisica.sefaz_nfce         == True,
        )
        query_pf = PessoaFisica.query.filter(
            PessoaFisica.active == True,
            sefaz_filter_pf
        )
        if current_user and current_user.is_authenticated:
            query_pf = query_pf.filter_by(id_empresa=current_user.empresa.id)
        empresas_pf = query_pf.all()
        
        lista = []
        for emp in empresas_pj:
            lista.append({
                "id": emp.id,
                "cnpj": emp.cnpj_cpf,
                "name": emp.name,
                "ie": emp.ie,
                "tipo": "PJ",
                "sefaz_nfe_saida": emp.sefaz_nfe_saida,
                "sefaz_nfe_entrada": emp.sefaz_nfe_entrada,
                "sefaz_cte_emitido": emp.sefaz_cte_emitido,
                "sefaz_cte_tomado": emp.sefaz_cte_tomado,
                "sefaz_nfce": emp.sefaz_nfce
            })
            
        for emp in empresas_pf:
            lista.append({
                "id": emp.id,
                "cnpj": emp.cnpj_cpf,
                "name": emp.name,
                "ie": emp.ie,
                "tipo": "PF",
                "sefaz_nfe_saida": emp.sefaz_nfe_saida,
                "sefaz_nfe_entrada": emp.sefaz_nfe_entrada,
                "sefaz_cte_emitido": emp.sefaz_cte_emitido,
                "sefaz_cte_tomado": emp.sefaz_cte_tomado,
                "sefaz_nfce": emp.sefaz_nfce
            })
            
        return jsonify({"success": True, "empresas": lista})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/salvar-comprovante', methods=['POST'])
@csrf.exempt
def api_salvar_comprovante():
    try:
        dados = request.get_json()
        cnpj = dados.get('cnpj')
        process = dados.get('process')
        month = dados.get('month')
        year = dados.get('year')
        filename = dados.get('filename')
        base64_data = dados.get('base64Data')
        run_id = dados.get('runId', 'ExtensionRun')
        tipo = dados.get('tipo')

        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]

        import base64
        file_bytes = base64.b64decode(base64_data)

        # Get company name and folder type
        tipo_pasta = "FISCAL PJ"
        empresa = PessoaJuridica.query.filter_by(cnpj_cpf=cnpj).first()
        if empresa:
            nome_empresa = empresa.name
            tipo_pasta = "FISCAL PJ"
        else:
            empresa_pf = PessoaFisica.query.filter_by(cnpj_cpf=cnpj).first()
            if empresa_pf:
                nome_empresa = empresa_pf.name
                tipo_pasta = "RURAL"
            else:
                nome_empresa = cnpj
                if tipo == 'PF' or len(cnpj) == 11:
                    tipo_pasta = "RURAL"
                else:
                    tipo_pasta = "FISCAL PJ"

        # Target directory structure
        month_str = str(month).zfill(2)
        pasta_destino = os.path.join(get_root_path(), 'OnixWeb', 'rpautomation', 'transactionFiles', run_id, nome_empresa, tipo_pasta, str(year), month_str, "Relatórios")
        os.makedirs(pasta_destino, exist_ok=True)

        target_path = os.path.join(pasta_destino, filename)
        with open(target_path, 'wb') as f:
            f.write(file_bytes)

        return jsonify({"success": True, "message": f"Comprovante salvo com sucesso em {target_path}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/registrar-download', methods=['POST'])
@csrf.exempt
def api_registrar_download():
    try:
        dados = request.get_json()
        cnpj = dados.get('cnpj')
        process = dados.get('process')
        month = dados.get('month')
        year = dados.get('year')
        filename = dados.get('filename') # relative path (e.g. "OnixDownloads/...")
        run_id = dados.get('runId', 'ExtensionRun')
        tipo = dados.get('tipo')

        import os
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        source_path = os.path.join(downloads_dir, filename.replace('/', os.sep))

        # Get company name and folder type
        tipo_pasta = "FISCAL PJ"
        empresa = PessoaJuridica.query.filter_by(cnpj_cpf=cnpj).first()
        if empresa:
            nome_empresa = empresa.name
            tipo_pasta = "FISCAL PJ"
        else:
            empresa_pf = PessoaFisica.query.filter_by(cnpj_cpf=cnpj).first()
            if empresa_pf:
                nome_empresa = empresa_pf.name
                tipo_pasta = "RURAL"
            else:
                nome_empresa = cnpj
                if tipo == 'PF' or len(cnpj) == 11:
                    tipo_pasta = "RURAL"
                else:
                    tipo_pasta = "FISCAL PJ"

        # Target directory matching original MT.py structure
        month_str = str(month).zfill(2)
        pasta_destino = os.path.join(get_root_path(), 'OnixWeb', 'rpautomation', 'transactionFiles', run_id, nome_empresa, tipo_pasta, str(year), month_str, "Relatórios")
        os.makedirs(pasta_destino, exist_ok=True)

        # Map target filename based on process to match original MT.py outputs perfectly!
        ext = os.path.splitext(source_path)[1] # e.g. .xlsx or .xls or .zip
        target_name = "Relatorio" + ext
        if process == 'nfe_saida':
            target_name = "Sefaz-Saidas" + ext
        elif process == 'nfe_entrada':
            target_name = "Sefaz-Entradas" + ext
        elif process == 'cte_emissor':
            target_name = "CT-e Emissor" + ext
        elif process == 'cte_tomador':
            target_name = "CT-e Tomador" + ext
        elif process == 'nfce':
            target_name = "NFCe Emitidas" + ext

        target_path = os.path.join(pasta_destino, target_name)

        # Wait and move file
        import shutil
        import time
        moved = False
        for _ in range(30): # Wait up to 30 seconds for chrome download to finish
            if os.path.exists(source_path) and os.path.getsize(source_path) > 0:
                try:
                    # Clean target path if it already exists
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    shutil.move(source_path, target_path)
                    moved = True
                    break
                except Exception as move_err:
                    print("Move error, retrying...", move_err)
            time.sleep(1)

        if moved:
            # ── Tratamento especial do ZIP NFCe (replica MT.py exec_NFCE) ────────────
            if process == 'nfce' and ext.lower() == '.zip':
                try:
                    import zipfile
                    import glob as glob_mod

                    # Passo 1: remover planilhas antigas antes de extrair (MT.py faz isso)
                    for old_f in (glob_mod.glob(os.path.join(pasta_destino, '*.xls')) +
                                  glob_mod.glob(os.path.join(pasta_destino, '*.xlsx'))):
                        bn = os.path.basename(old_f)
                        if 'Planilha' in bn or 'NFCe Emitidas' in bn:
                            try:
                                os.remove(old_f)
                            except Exception:
                                pass

                    # Passo 2: extrair ZIP para pasta de destino
                    with zipfile.ZipFile(target_path, 'r') as zip_ref:
                        zip_ref.extractall(pasta_destino)

                    # Passo 3: deletar o ZIP (já extraído — MT.py não mantém o zip)
                    if os.path.exists(target_path):
                        os.remove(target_path)

                    # Passo 4: encontrar a planilha extraída e renomear para "NFCe Emitidas.xls"
                    # Busca recursiva para cobrir ZIPs com subpastas internas
                    # Padrão MT.py: NomeParcialPlanilha = 'Planilha'
                    extracted_renamed = False
                    candidatos = (
                        glob_mod.glob(os.path.join(pasta_destino, '**', '*.xls'),  recursive=True) +
                        glob_mod.glob(os.path.join(pasta_destino, '**', '*.xlsx'), recursive=True)
                    )
                    for arq_p in candidatos:
                        bn = os.path.basename(arq_p)
                        if 'Planilha' in bn or 'ConsultaNFCe' in bn or 'NFCeEmitida' in bn:
                            novo_nome = os.path.join(pasta_destino, 'NFCe Emitidas.xls')
                            if os.path.exists(novo_nome):
                                os.remove(novo_nome)
                            shutil.move(arq_p, novo_nome)
                            extracted_renamed = True
                            break

                    if extracted_renamed:
                        return jsonify({
                            "success": True,
                            "message": f"NFCe ZIP extraído e planilha salva como 'NFCe Emitidas.xls' em {pasta_destino}"
                        })
                    else:
                        # ZIP extraído mas planilha não encontrada pelo padrão esperado
                        # Registrar quais arquivos foram extraídos para diagnóstico
                        restantes = [os.path.basename(f) for f in
                                     glob_mod.glob(os.path.join(pasta_destino, '**', '*.*'), recursive=True)]
                        print(f"[NFCe] ZIP extraído mas planilha não localizada. Arquivos em pasta: {restantes}")
                        return jsonify({
                            "success": True,
                            "message": f"ZIP extraído mas planilha não renomeada. Arquivos presentes: {restantes}"
                        })

                except Exception as zip_err:
                    print(f"[NFCe] Erro ao processar ZIP: {zip_err}")
                    # Manter o ZIP em caso de erro para diagnóstico manual
                    return jsonify({"success": False, "error": f"Erro ao extrair ZIP NFCe: {str(zip_err)}"}), 500

            return jsonify({"success": True, "message": f"Arquivo sincronizado com sucesso em {target_path}"})
        else:
            return jsonify({"success": False, "error": f"Arquivo não encontrado em {source_path}"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/iniciar-rpa', methods=['POST'])
@csrf.exempt
def api_iniciar_rpa():
    try:
        dados = request.get_json()
        run_id = dados.get('runId')
        
        # Add or reset in ThreadingCounter
        counter = ThreadingCounter.query.filter_by(thread_name=run_id).first()
        if not counter:
            counter = ThreadingCounter()
            counter.thread_name = run_id
            counter.percentil = 5
            db.session.add(counter)
        else:
            counter.percentil = 5
        db.session.commit()

        # Add initial log entry matching Selenium script logs
        data = logData()
        data.thread_name = run_id
        data.log_title = "RPA INICIADO"
        data.log_desc = "Automação iniciada via Extensão Chrome Manifest V3 (Bypass WAF)."
        data.cnpj_cpf = "BOT"
        data.data = datetime.now()
        data.tipo = "BOT"
        data.bg_tipo = "primary-gradient"
        data.status = "SUCESSO"
        data.bg_status = "success-gradient"
        db.session.add(data)
        db.session.commit()

        return jsonify({"success": True, "message": "Fila iniciada e registrada no banco de dados."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/log-rpa', methods=['POST'])
@csrf.exempt
def api_log_rpa():
    try:
        dados = request.get_json()
        run_id = dados.get('runId')
        log_title = dados.get('log_title')
        log_desc = dados.get('log_desc')
        cnpj_cpf = dados.get('cnpj_cpf', 'BOT')
        tipo = dados.get('tipo', 'BOT')
        bg_tipo = dados.get('bg_tipo', 'primary-gradient')
        status = dados.get('status', 'SUCESSO')
        bg_status = dados.get('bg_status', 'success-gradient')

        data = logData()
        data.thread_name = run_id
        data.log_title = log_title
        data.log_desc = log_desc
        data.cnpj_cpf = cnpj_cpf
        data.data = datetime.now()
        data.tipo = tipo
        data.bg_tipo = bg_tipo
        data.status = status
        data.bg_status = bg_status
        db.session.add(data)
        db.session.commit()

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/update-progress', methods=['POST'])
@csrf.exempt
def api_update_progress():
    try:
        dados = request.get_json()
        run_id = dados.get('runId')
        percentil = dados.get('percentil')

        counter = ThreadingCounter.query.filter_by(thread_name=run_id).first()
        if counter:
            counter.percentil = int(percentil)
            db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/finalizar-rpa', methods=['POST'])
@csrf.exempt
def api_finalizar_rpa():
    try:
        dados = request.get_json()
        run_id = dados.get('runId')

        # Zip transactionFiles/{run_id} folder to transactionFiles/{run_id}.zip
        caminho_pasta = os.path.join(get_root_path(), 'OnixWeb', 'rpautomation', 'transactionFiles', run_id)
        
        # Check if directory exists
        if os.path.exists(caminho_pasta):
            import shutil
            # Make zip file C:\Onix\Onix\OnixWeb\rpautomation\transactionFiles\{run_id}.zip
            shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
            
            # Clean up unzipped folder
            shutil.rmtree(caminho_pasta, ignore_errors=True)

        # Update ThreadingCounter to 100
        counter = ThreadingCounter.query.filter_by(thread_name=run_id).first()
        if counter:
            counter.percentil = 100
            db.session.commit()

        # Add final log entry
        data = logData()
        data.thread_name = run_id
        data.log_title = "RPA FINALIZADO"
        data.log_desc = "Fila e processos concluídos. Arquivo ZIP de relatórios gerado e disponível!"
        data.cnpj_cpf = "BOT"
        data.data = datetime.now()
        data.tipo = "BOT"
        data.bg_tipo = "primary-gradient"
        data.status = "SUCESSO"
        data.bg_status = "success-gradient"
        db.session.add(data)
        db.session.commit()

        return jsonify({"success": True, "message": f"Fila concluída e ZIP gerado para a execução {run_id}."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/configurar-servidor', methods=['POST'])
@csrf.exempt
def api_configurar_servidor():
    try:
        from flask import current_app
        from sqlalchemy import create_engine
        
        dados = request.get_json()
        db_path = dados.get('dbPath')
        custom_root = dados.get('rootPath')
        
        global CUSTOM_DB_PATH, CUSTOM_ROOT_PATH
        
        response_messages = []
        
        if db_path:
            db_path = db_path.strip()
            abs_db_path = os.path.abspath(db_path)
            new_uri = 'sqlite:///' + abs_db_path
            
            # Atualizar URI da base de dados do Flask
            current_app.config['SQLALCHEMY_DATABASE_URI'] = new_uri
            
            # Desconectar conexões antigas do banco
            db.engine.dispose()
            
            # Recriar engine e vincular à sessão
            db.engine = create_engine(new_uri)
            db.session.remove()
            db.session.configure(bind=db.engine)
            
            # Garantir existência de tabelas caso seja nova base
            db.create_all()
            
            CUSTOM_DB_PATH = abs_db_path
            response_messages.append(f"Banco alterado para: {abs_db_path}")
            
        if custom_root:
            custom_root = custom_root.strip()
            abs_root = os.path.abspath(custom_root)
            os.makedirs(abs_root, exist_ok=True)
            CUSTOM_ROOT_PATH = abs_root
            response_messages.append(f"Pasta alterada para: {abs_root}")
            
        db_current = CUSTOM_DB_PATH if CUSTOM_DB_PATH else current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        root_current = CUSTOM_ROOT_PATH if CUSTOM_ROOT_PATH else os.path.abspath('')
        
        return jsonify({
            "success": True, 
            "message": " | ".join(response_messages) if response_messages else "Configurações sincronizadas.",
            "dbPath": os.path.abspath(db_current),
            "rootPath": os.path.abspath(root_current)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint.route('/api/configurar-servidor', methods=['GET'])
def api_obter_configuracao():
    try:
        from flask import current_app
        global CUSTOM_DB_PATH, CUSTOM_ROOT_PATH
        
        db_current = CUSTOM_DB_PATH if CUSTOM_DB_PATH else current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        root_current = CUSTOM_ROOT_PATH if CUSTOM_ROOT_PATH else os.path.abspath('')
        
        return jsonify({
            "success": True,
            "dbPath": os.path.abspath(db_current),
            "rootPath": os.path.abspath(root_current)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
