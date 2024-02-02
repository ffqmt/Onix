# -*- encoding: utf-8 -*-
import os
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

from OnixWeb import db, login_manager
from OnixWeb.addons.agendamentos import scheduler, agendamentoAddSchenduler
from OnixWeb.addons.util import get_segment, log_message
from OnixWeb.aditional_routes import blueprint
from OnixWeb.addons.models import Users, Empresas, PessoaJuridica, City, PessoaFisica, ThreadingCounter, logData, UF, \
    AgendamentosRPA
from OnixWeb.rpautomation.prefeituras import MT_1
from OnixWeb.rpautomation.sefaz import MT

basedir = os.path.abspath('')
root_path = os.path.abspath('')


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

        codigo_unico = datetime.now().strftime("%Y%m%d%H%M%S%f")
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
                caminho_arquivo = f'{root_path}/OnixWeb/rpautomation/transactionFiles/' + arquivo
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

        codigo_unico = datetime.now().strftime("%Y%m%d%H%M%S%f")
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
                [f"O dia e hora informado não pode ser igual a dia e hora atual, agendamento não foi cadastrado.", "OK", "", "mensagem"],
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
