"""
Busca a previsão do tempo pra cidade do estádio, na hora do jogo.
Usa a Open-Meteo (gratuita, sem necessidade de chave de API) —
serviço diferente da API-Football, só pra esse dado específico.
"""
import requests
import streamlit as st


@st.cache_data(ttl=3600)
def _obter_coordenadas(cidade: str):
    if not cidade:
        return None
    resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": cidade, "count": 1},
        timeout=10,
    )
    resp.raise_for_status()
    resultados = resp.json().get("results")
    if not resultados:
        return None
    r = resultados[0]
    return r["latitude"], r["longitude"]


@st.cache_data(ttl=3600)
def obter_clima(cidade: str, data_hora_iso: str):
    """
    Retorna temperatura, chuva (mm) e vento (km/h) previstos pra hora do jogo.
    Retorna None se não conseguir localizar a cidade ou não houver previsão.
    """
    coordenadas = _obter_coordenadas(cidade)
    if not coordenadas:
        return None
    lat, lon = coordenadas
    data = data_hora_iso[:10]

    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "start_date": data,
            "end_date": data,
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    dados = resp.json()
    horas = dados.get("hourly", {}).get("time", [])
    if not horas:
        return None

    hora_alvo = data_hora_iso[:13]
    indice = 0
    for i, h in enumerate(horas):
        if h.startswith(hora_alvo):
            indice = i
            break

    return {
        "temperatura": dados["hourly"]["temperature_2m"][indice],
        "chuva_mm": dados["hourly"]["precipitation"][indice],
        "vento_kmh": dados["hourly"]["wind_speed_10m"][indice],
    }


def interpretar_clima(clima: dict) -> str:
    """Transforma os números do clima numa nota de analista sobre o possível impacto no jogo."""
    if not clima:
        return ""
    notas = []
    if clima["chuva_mm"] and clima["chuva_mm"] >= 2:
        notas.append("chuva prevista pode deixar o jogo mais truncado e favorecer menos gols")
    if clima["vento_kmh"] and clima["vento_kmh"] >= 30:
        notas.append("vento forte pode atrapalhar bolas aéreas e finalizações de longe")
    if clima["temperatura"] is not None and clima["temperatura"] >= 32:
        notas.append("calor intenso pode reduzir o ritmo no segundo tempo")
    if not notas:
        return "Condições climáticas dentro do normal, sem impacto relevante esperado."
    return "Atenção: " + "; ".join(notas) + "."
