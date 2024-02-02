# -*- encoding: utf-8 -*-
import glob
import os
import hashlib
import binascii
from collections import defaultdict
from datetime import datetime
from flask import request
from flask_login import current_user
from sqlalchemy import inspect


def hash_pass(password):
    # return password  # SEM ENCRYPT

    # PARA ENCRYPT
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'),
                                  salt, 100000)
    pwdhash = binascii.hexlify(pwdhash)
    return salt + pwdhash  # return bytes


def verify_pass(provided_password, stored_password):
    # return provided_password == stored_password  # SEM ENCRYPT

    # PARA ENCRYPT
    stored_password = stored_password.decode('ascii')
    salt = stored_password[:64]
    stored_password = stored_password[64:]
    pwdhash = hashlib.pbkdf2_hmac('sha512',
                                  provided_password.encode('utf-8'),
                                  salt.encode('ascii'),
                                  100000)
    pwdhash = binascii.hexlify(pwdhash).decode('ascii')
    return pwdhash == stored_password


def get_segment(request_page):
    try:
        segment = request_page.path.split('/')[-1]
        return segment
    except Exception:
        return None


def query_to_dict(rset):
    result = defaultdict(list)
    for obj in rset:
        instance = inspect(obj)
        for key, x in instance.attrs.items():
            result[key].append(x.value)
    return result


def log_message(level='INFO'):
    agora = datetime.now()
    log_time = agora.strftime("%d/%m/%Y %H:%M")
    try:
        userlog = current_user.username
    except Exception:
        userlog = "Anônimo"
    msg = f"Method: {request.method} -> Tela '{get_segment(request)}' - Acessada por: {userlog}"
    log_message_final = f'{log_time} [{level}] {msg}'
    with open('log.txt', 'a') as file:
        print(log_message_final, file=file)


def verify_downloaded(path):
    if os.path.exists(path):
        return True
    else:
        return False


def limpar_pasta(path):
    try:
        remover_a = glob.glob(os.path.join(path, '*.htm'))
        for arquivo in remover_a:
            os.remove(arquivo)
        remover_b = glob.glob(os.path.join(path, '*.crdownload'))
        for arquivo in remover_b:
            os.remove(arquivo)
        remover_c = glob.glob(os.path.join(path, '*.zip'))
        for arquivo in remover_c:
            os.remove(arquivo)
        print('Limpeza de pasta realizada com sucesso!')
    except Exception:
        print('Limpeza de pasta não realizada!')
