import os
import json
from flask import Flask, request, render_template, redirect, url_for, session, flash, send_file, jsonify
from datetime import timedelta, datetime
import re
import pandas as pd
import requests
import random

# Importa a função de autenticação do seu outro arquivo

app = Flask(__name__)
app.secret_key = 'segredo-supersecreto'
app.permanent_session_lifetime = timedelta(minutes=30)

# --- ATENÇÃO: Substitua pela URL correta da API para consultar um paciente ---
URL_CONSULTA_PACIENTE = 'https://amei.amorsaude.com.br/api/v1/patients/document/{}' # O {} será trocado pelo CPF

# Caminhos dos arquivos
USUARIOS_FILE = 'atendente/usuarios.json'
SORTEIOS_FILE = 'atendente/sorteios.json'
FILIADOS_FILE = 'atendente/filiados.json' 
PREMIOS_FILE = 'atendente/premios.json'

# ---------------------- Funções auxiliares ----------------------

def carregar_json(caminho_arquivo):
    if not os.path.exists(caminho_arquivo):
        return []
    with open(caminho_arquivo, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def carregar_usuarios():
    if os.path.exists(USUARIOS_FILE):
        with open(USUARIOS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def sortear_premio_ponderado():
    """Lê os prêmios e suas chances do arquivo JSON e sorteia um."""
    premios_config = carregar_json(PREMIOS_FILE)
    
    if not premios_config:
        # Retorna um prêmio padrão caso o arquivo não exista ou esteja vazio
        return "Prêmio Padrão"

    nomes_premios = [p['nome'] for p in premios_config]
    chances = [p['chance'] for p in premios_config]
    
    # A função random.choices faz o sorteio ponderado. k=1 significa que queremos 1 resultado.
    premio_sorteado = random.choices(nomes_premios, weights=chances, k=1)[0]
    return premio_sorteado

def verificar_login(username, password):
    usuarios = carregar_usuarios()
    for u in usuarios:
        if u["username"] == username and u["password"] == password:
            return u["role"]
    return None

def limpar_cpf(cpf):
    return re.sub(r'\D', '', cpf)

def carregar_sorteios():
    if os.path.exists(SORTEIOS_FILE):
        with open(SORTEIOS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def salvar_sorteios(lista):
    with open(SORTEIOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(lista, f, indent=2, ensure_ascii=False)

def salvar_json(caminho_arquivo, dados):
    """Função genérica para salvar dados em um arquivo JSON."""
    with open(caminho_arquivo, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)

# ---------------------- Rotas principais ------------------------

@app.route('/', methods=['GET'])
def home():
    return redirect(url_for('roleta'))

@app.route('/roleta', methods=['GET', 'POST'])
def roleta():
    # Se for um GET (primeiro acesso à página), carrega os prêmios e renderiza o HTML
    if request.method == 'GET':
        premios = carregar_json(PREMIOS_FILE)
        return render_template("index.html", premios=premios)

    # Se for um POST, processa a lógica
    resultado = None
    erro = None
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    cpf = limpar_cpf(request.form.get('cpf', ''))
    if len(cpf) != 11:
        erro = "CPF inválido. Digite 11 números."
        if is_ajax: return jsonify({"success": False, "erro": erro})
        return render_template("index.html", erro=erro)

    filiados_autorizados = carregar_json(FILIADOS_FILE)
    filiado_info = next((f for f in filiados_autorizados if f.get('cpf') == cpf), None)
    
    if not filiado_info:
        erro = "CPF não consta na lista de participantes. Fale com um atendente."
        if is_ajax: return jsonify({"success": False, "erro": erro})
    else:
        sorteios = carregar_json(SORTEIOS_FILE)
        ja_sorteado = next((s for s in sorteios if s.get('cpf') == cpf), None)

        if ja_sorteado:
            resultado = {
                "premio": ja_sorteado.get('premio'),
                "data": ja_sorteado.get('data_sorteio')
            }
        else:
            premio_ganho = sortear_premio_ponderado()
            data_do_sorteio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            resultado = { "premio": premio_ganho, "data": data_do_sorteio }
            sorteios.append({
                "cpf": cpf,
                "premio": premio_ganho,
                "data_sorteio": data_do_sorteio,
                "atendente_cadastro": filiado_info.get('cadastrado_por', 'N/A')
            })
            salvar_json(SORTEIOS_FILE, sorteios)
    
    if is_ajax:
        if erro:
            return jsonify({"success": False, "erro": erro})
        else:
            return jsonify({"success": True, "resultado": resultado})

    # Fallback para o caso de um POST não-ajax
    premios = carregar_json(PREMIOS_FILE)
    return render_template("index.html", resultado=resultado, erro=erro, premios=premios)

@app.route('/exportar-sorteios-excel')
def exportar_sorteios_excel():
    if "usuario" not in session:
        return redirect(url_for('login'))

    sorteios = carregar_sorteios()
    df = pd.DataFrame(sorteios)
    excel_path = 'atendente/sorteios_exportados.xlsx'
    df.to_excel(excel_path, index=False)

    return send_file(excel_path, as_attachment=True)

@app.route('/exportar-usuarios-json')
def exportar_usuarios_json():
    if "usuario" not in session or session.get("role") != "admin":
        flash("Apenas administradores podem acessar essa função.", "danger")
        return redirect(url_for('painel'))
    return send_file(USUARIOS_FILE, as_attachment=True)

@app.route('/cadastrar-cpf', methods=['GET', 'POST'])
def cadastrar_cpf():
    if "usuario" not in session:
        return redirect(url_for('login'))

    mensagem = None
    if request.method == 'POST':
        cpf = limpar_cpf(request.form.get('cpf', ''))

        if len(cpf) != 11:
            mensagem = "CPF inválido. Deve conter 11 números."
        else:
            filiados = carregar_json(FILIADOS_FILE)
            # LÓGICA ATUALIZADA: Verifica se já existe um objeto com aquele CPF
            if any(f.get('cpf') == cpf for f in filiados):
                mensagem = "Este CPF já está na lista de autorizados."
            else:
                # LÓGICA ATUALIZADA: Salva um objeto completo
                filiados.append({
                    "cpf": cpf,
                    "cadastrado_por": session.get("usuario", "desconhecido"),
                    "data_cadastro": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                })
                salvar_json(FILIADOS_FILE, filiados)
                mensagem = "CPF autorizado para o sorteio com sucesso!"

    return render_template("cadastrar_cpf.html", mensagem=mensagem)

@app.route('/exportar-sorteios-json')
def exportar_sorteios_json():
    if "usuario" not in session:
        return redirect(url_for('login'))
    return send_file(SORTEIOS_FILE, as_attachment=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get("username")
        password = request.form.get("password")

        role = verificar_login(username, password)

        if role:
            session["usuario"] = username
            session["role"] = role
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for('painel'))
        else:
            flash("Usuário ou senha inválidos.", "danger")

    return render_template("login.html")

@app.route('/painel')
def painel():
    if "usuario" not in session:
        flash("Faça login para acessar o painel.", "warning")
        return redirect(url_for("login"))

    usuario = session["usuario"]
    role = session["role"]
    
    return render_template("painel.html", usuario=usuario, role=role)

@app.route('/logout')
def logout():
    session.clear()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("login"))

@app.route('/cadastrar-usuario', methods=['GET', 'POST'])
def cadastrar_usuario():
    if "usuario" not in session or session.get("role") != "admin":
        flash("Apenas administradores podem acessar essa função.", "danger")
        return redirect(url_for('painel'))

    mensagem = None

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        if not username or not password or role not in ["admin", "user"]:
            mensagem = "Dados inválidos."
        else:
            usuarios = carregar_usuarios()
            if any(u['username'] == username for u in usuarios):
                mensagem = "Usuário já existe."
            else:
                usuarios.append({
                    "username": username,
                    "password": password,
                    "role": role
                })
                with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(usuarios, f, indent=2, ensure_ascii=False)
                mensagem = "Usuário cadastrado com sucesso!"

    return render_template("cadastrar_usuario.html", mensagem=mensagem)

# ---------------------- Inicialização ---------------------------

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)