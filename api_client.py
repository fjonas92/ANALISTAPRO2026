"""
Cliente de acesso à API-Football (v3).
Todas as chamadas HTTP à API ficam centralizadas aqui.
"""
import time
import requests
import streamlit as st

BASE_URL = "https://v3.football.api-sports.io"


def _headers():
    return {"x-apisports-key": st.secrets["API_FOOTBALL_KEY"]}


@st.cache_data(ttl=1800)
def buscar_jogos_do_dia(data: str, timezone: str = "America/Sao_Paulo"):
    params = {"date": data, "timezone": timezone}
    resp = requests.get(f"{BASE_URL}/fixtures", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", [])


@st.cache_data(ttl=1800)
def obter_estatisticas_temporada(team_id: int, league_id: int, season: int):
    """Estatísticas completas do time na liga/temporada: forma, gols casa/fora, clean sheets etc."""
    params = {"team": team_id, "league": league_id, "season": season}
    resp = requests.get(f"{BASE_URL}/teams/statistics", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", {})


@st.cache_data(ttl=1800)
def obter_odds_pre_jogo(fixture_id: int):
    """Odds pré-jogo (esse endpoint não retorna odds ao vivo)."""
    params = {"fixture": fixture_id}
    resp = requests.get(f"{BASE_URL}/odds", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", [])


@st.cache_data(ttl=1800)
def obter_standings(league_id: int, season: int):
    """
    Tabela de classificação da liga. Vem organizada em 'grupos' (mesmo em ligas
    sem fase de grupos, é só um grupo). Achatamos tudo numa lista única de times.
    """
    params = {"league": league_id, "season": season}
    resp = requests.get(f"{BASE_URL}/standings", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    dados = resp.json().get("response", [])
    if not dados:
        return []
    grupos = dados[0]["league"]["standings"]
    lista_achatada = []
    for grupo in grupos:
        lista_achatada.extend(grupo)
    return lista_achatada


def obter_posicao_time(standings_lista: list, team_id: int):
    """Procura, na lista de classificação já buscada, a entrada de um time específico."""
    for time_info in standings_lista:
        if time_info["team"]["id"] == team_id:
            return time_info
    return None


@st.cache_data(ttl=1800)
def obter_h2h(casa_id: int, fora_id: int, ultimos: int = 5):
    """Últimos confrontos diretos entre os dois times, independente de mando de campo."""
    params = {"h2h": f"{casa_id}-{fora_id}", "last": ultimos}
    resp = requests.get(f"{BASE_URL}/fixtures/headtohead", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", [])


@st.cache_data(ttl=1800)
def obter_lesoes(fixture_id: int):
    """Jogadores lesionados/suspensos relacionados a essa partida específica."""
    params = {"fixture": fixture_id}
    resp = requests.get(f"{BASE_URL}/injuries", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", [])


@st.cache_data(ttl=1800)
def obter_ultimos_fixture_ids(team_id: int, quantidade: int = 5):
    params = {"team": team_id, "last": quantidade}
    resp = requests.get(f"{BASE_URL}/fixtures", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", [])


@st.cache_data(ttl=600)
def obter_escalacoes(fixture_id: int):
    """
    Escalações confirmadas do jogo. Só costumam aparecer perto do horário
    da partida (normalmente ~1h antes) — antes disso, vem vazio.
    """
    params = {"fixture": fixture_id}
    resp = requests.get(f"{BASE_URL}/fixtures/lineups", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("response", [])


@st.cache_data(ttl=3600)
def obter_estatisticas_avancadas(team_id: int, quantidade: int = 5):
    """
    Calcula, a partir dos últimos N jogos do time, a média de: escanteios,
    chutes totais, chutes no alvo, faltas cometidas e faltas sofridas.
    ATENÇÃO: função cara — gasta 1 requisição extra por jogo (endpoint
    /fixtures/statistics). Como já precisamos passar por esses jogos pra
    pegar escanteios, aproveitamos a mesma passada pra pegar tudo de uma vez.
    """
    jogos = obter_ultimos_fixture_ids(team_id, quantidade)
    somas = {"escanteios": 0, "chutes_totais": 0, "chutes_alvo": 0, "faltas_cometidas": 0, "faltas_sofridas": 0}
    contagens = {chave: 0 for chave in somas}

    mapa_tipos = {
        "Corner Kicks": "escanteios",
        "Total Shots": "chutes_totais",
        "Shots on Goal": "chutes_alvo",
        "Fouls": "faltas_cometidas",
    }

    for jogo in jogos:
        fixture_id = jogo["fixture"]["id"]
        resp = requests.get(f"{BASE_URL}/fixtures/statistics", headers=_headers(), params={"fixture": fixture_id}, timeout=15)
        resp.raise_for_status()
        estatisticas = resp.json().get("response", [])

        for lado in estatisticas:
            eh_o_time = lado["team"]["id"] == team_id
            for item in lado.get("statistics", []):
                chave = mapa_tipos.get(item["type"])
                if chave and item["value"] is not None:
                    if eh_o_time:
                        somas[chave] += item["value"]
                        contagens[chave] += 1
                    elif item["type"] == "Fouls":
                        # Faltas cometidas pelo ADVERSÁRIO nesse jogo = faltas sofridas por esse time
                        somas["faltas_sofridas"] += item["value"]
                        contagens["faltas_sofridas"] += 1
        time.sleep(0.4)  # espaça as chamadas pra não estourar o limite por minuto da API

    return {
        chave: round(somas[chave] / contagens[chave], 2) if contagens[chave] else None
        for chave in somas
    }
