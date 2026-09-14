import streamlit as st
from datetime import datetime, timedelta
import pytz

from api_client import (
    buscar_jogos_do_dia, obter_estatisticas_temporada, obter_odds_pre_jogo,
    obter_standings, obter_posicao_time, obter_h2h, obter_lesoes,
    obter_estatisticas_avancadas,
)
from analise import gerar_dicas_do_jogo, resumir_h2h, montar_contexto_lesoes, montar_contexto_forca, montar_contexto_avancado
from clima import obter_clima, interpretar_clima

# Controle interno (não aparece pro visitante do site): liga/desliga a busca de
# chutes/faltas/escanteios, que custa ~10 requisições extras por jogo analisado.
# Mude pra True só se quiser testar localmente — em produção, deixe False pra
# não gastar a cota diária da API rápido demais com muitos visitantes.
ATIVAR_ESTATISTICAS_AVANCADAS = False

st.set_page_config(page_title="ANALISTA PRO", page_icon="⚽", layout="wide")

# ---------- TELA DE ACESSO (chave de licença) ----------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.title("⚽ ANALISTA PRO")
    st.subheader("Acesso restrito")
    codigo_digitado = st.text_input("Digite sua chave de licença:", type="password")

    if st.button("Entrar"):
        licencas_validas = st.secrets.get("LICENCAS", {})
        if codigo_digitado in licencas_validas:
            st.session_state.autenticado = True
            st.rerun()
        else:
            st.error("Chave inválida. Confira o código ou entre em contato pra obter acesso.")

    st.stop()  # Impede que o resto do site carregue sem autenticação

# ---------- ESTILO DOS CARDS ----------
st.markdown(
    """
    <style>
    .card-dica { background-color: #1a2436; border-radius: 10px; padding: 14px; margin-bottom: 10px; color: #f8fafc; }
    .card-dica * { color: #f8fafc !important; }
    .card-contexto { background-color: #1a2436; border-radius: 10px; padding: 12px; margin-bottom: 14px; font-size: 0.92em; color: #f8fafc; }
    .card-contexto * { color: #f8fafc !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

CORES_CONFIANCA = {"Alta": "🟢", "Média": "🟡", "Baixa": "🔴"}

st.title("⚽ ANALISTA PRO")

# ---------- SELEÇÃO DE DATA ----------
opcao = st.radio("Selecione:", ["Jogos de Hoje", "Jogos de Amanhã"], horizontal=True)

fuso = pytz.timezone("America/Sao_Paulo")
hoje = datetime.now(fuso)
data_alvo = hoje if opcao == "Jogos de Hoje" else hoje + timedelta(days=1)
data_str = data_alvo.strftime("%Y-%m-%d")

with st.spinner("Buscando jogos..."):
    jogos = buscar_jogos_do_dia(data_str)

if not jogos:
    st.warning("Nenhum jogo encontrado para essa data.")
    st.stop()

# ---------- FILTRO DE LIGA ----------
def _rotulo_liga(j):
    return f"{j['league']['country']} - {j['league']['name']}"

ligas_disponiveis = sorted({_rotulo_liga(j) for j in jogos})
ligas_selecionadas = st.multiselect("Filtrar por liga:", ligas_disponiveis)

jogos_filtrados = [j for j in jogos if not ligas_selecionadas or _rotulo_liga(j) in ligas_selecionadas]

st.write(f"**{len(jogos_filtrados)} jogos encontrados**")

if "analises" not in st.session_state:
    st.session_state.analises = {}

for jogo in jogos_filtrados:
    casa = jogo["teams"]["home"]["name"]
    fora = jogo["teams"]["away"]["name"]
    casa_id = jogo["teams"]["home"]["id"]
    fora_id = jogo["teams"]["away"]["id"]
    liga = jogo["league"]["name"]
    liga_id = jogo["league"]["id"]
    temporada = jogo["league"]["season"]
    fixture_id = jogo["fixture"]["id"]

    horario_utc = jogo["fixture"]["date"]
    horario_local_dt = datetime.fromisoformat(horario_utc).astimezone(fuso)
    horario_local = horario_local_dt.strftime("%H:%M")

    with st.expander(f"{casa} x {fora} — {liga} — {horario_local}"):
        resultado_salvo = st.session_state.analises.get(fixture_id)

        if resultado_salvo is None:
            if st.button("🔎 Analisar este jogo", key=f"btn_{fixture_id}"):
                try:
                    home_stats = obter_estatisticas_temporada(casa_id, liga_id, temporada)
                    away_stats = obter_estatisticas_temporada(fora_id, liga_id, temporada)
                    odds = obter_odds_pre_jogo(fixture_id)

                    standings_lista = obter_standings(liga_id, temporada)
                    standings_casa = obter_posicao_time(standings_lista, casa_id)
                    standings_fora = obter_posicao_time(standings_lista, fora_id)

                    h2h_lista = obter_h2h(casa_id, fora_id)
                    h2h_resumo = resumir_h2h(h2h_lista, casa_id)

                    lesoes_lista = obter_lesoes(fixture_id)
                    contexto_lesoes = montar_contexto_lesoes(lesoes_lista, casa_id, fora_id, casa, fora)

                    venue_cidade = (jogo.get("fixture", {}).get("venue") or {}).get("city")
                    clima = obter_clima(venue_cidade, horario_utc) if venue_cidade else None

                    avancadas_casa = avancadas_fora = None
                    escanteios_casa = escanteios_fora = None
                    if ATIVAR_ESTATISTICAS_AVANCADAS:
                        avancadas_casa = obter_estatisticas_avancadas(casa_id)
                        avancadas_fora = obter_estatisticas_avancadas(fora_id)
                        escanteios_casa = avancadas_casa.get("escanteios")
                        escanteios_fora = avancadas_fora.get("escanteios")

                    dicas = gerar_dicas_do_jogo(
                        home_stats, away_stats, casa, fora, odds,
                        standings_casa=standings_casa, standings_fora=standings_fora,
                        h2h_resumo=h2h_resumo,
                        escanteios_casa=escanteios_casa, escanteios_fora=escanteios_fora,
                    )

                    st.session_state.analises[fixture_id] = {
                        "ok": True,
                        "dicas": dicas,
                        "contexto_lesoes": contexto_lesoes,
                        "contexto_forca": montar_contexto_forca(home_stats, away_stats, casa, fora),
                        "contexto_avancado": montar_contexto_avancado(avancadas_casa, avancadas_fora, casa, fora),
                        "clima": clima,
                    }
                except Exception as erro:
                    if "429" in str(erro):
                        mensagem = "Um dos serviços externos está limitando requisições. Espere alguns segundos e clique em Analisar de novo."
                    else:
                        mensagem = f"Não foi possível analisar esse jogo agora (dados insuficientes na API). Detalhe: {erro}"
                    st.session_state.analises[fixture_id] = {"ok": False, "erro": mensagem}
                st.rerun()

        elif resultado_salvo["ok"]:
            # ---------- BLOCO DE CONTEXTO ----------
            partes_contexto = [resultado_salvo["contexto_lesoes"], "💪 " + resultado_salvo["contexto_forca"]]

            if resultado_salvo.get("contexto_avancado"):
                partes_contexto.append("📈 " + resultado_salvo["contexto_avancado"])

            if resultado_salvo["clima"]:
                partes_contexto.append("🌤️ " + interpretar_clima(resultado_salvo["clima"]))

            st.markdown(
                f'<div class="card-contexto">{"<br>".join(partes_contexto)}</div>',
                unsafe_allow_html=True,
            )

            # ---------- AS 3 DICAS ----------
            for dica in resultado_salvo["dicas"]:
                emoji = CORES_CONFIANCA.get(dica["confianca"], "⚪")
                odd_texto = dica["odd"] if dica["odd"] else "indisponível"
                probabilidade_texto = f"{dica['confianca_pct']:.0f}%"

                st.markdown(
                    f"""
                    <div class="card-dica">
                    <b>{emoji} {dica['confianca']} confiança — {dica['mercado']}: {dica['escolha']}</b><br>
                    Nossa probabilidade estimada: <b>{probabilidade_texto}</b> &nbsp;|&nbsp; Odd de mercado: <b>{odd_texto}</b><br><br>
                    {dica['narrativa']}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.error(resultado_salvo["erro"])
            if st.button("Tentar de novo", key=f"retry_{fixture_id}"):
                del st.session_state.analises[fixture_id]
                st.rerun()
