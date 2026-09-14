"""
Guarda um histórico local das odds vistas, pra detectar movimentação
e variações anormais ao longo do tempo (ex: uma odd que despenca de
repente pode indicar notícia de bastidor, como lesão de última hora).

Fica salvo num arquivo simples (odds_historico.json) na pasta do projeto.
Isso significa que a comparação só fica interessante depois de você
abrir o site em momentos diferentes pro mesmo jogo (ex: de manhã e à tarde).
"""
import json
import os

CAMINHO_HISTORICO = "odds_historico.json"


def _carregar():
    if not os.path.exists(CAMINHO_HISTORICO):
        return {}
    try:
        with open(CAMINHO_HISTORICO, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def _salvar(dados):
    with open(CAMINHO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def registrar_e_comparar(fixture_id, mercado, valor, odd_atual):
    """
    Na primeira vez que vê essa combinação de jogo+mercado+escolha, guarda a odd.
    Nas vezes seguintes, calcula a variação % em relação à primeira odd vista.
    """
    if odd_atual is None:
        return None

    historico = _carregar()
    chave = f"{fixture_id}_{mercado}_{valor}"
    registro = historico.get(chave)

    if registro is None:
        historico[chave] = {"odd_inicial": odd_atual}
        _salvar(historico)
        return {"variacao_pct": 0.0, "anormal": False, "odd_inicial": float(odd_atual)}

    odd_inicial = float(registro["odd_inicial"])
    variacao_pct = ((float(odd_atual) - odd_inicial) / odd_inicial) * 100
    return {
        "variacao_pct": round(variacao_pct, 1),
        "anormal": abs(variacao_pct) >= 15,
        "odd_inicial": odd_inicial,
    }


def probabilidade_implicita(odd) -> float:
    """Converte odd decimal em probabilidade implícita (%). Ex: odd 2.00 -> 50%."""
    if not odd:
        return None
    try:
        return round((1 / float(odd)) * 100, 1)
    except (ValueError, ZeroDivisionError):
        return None
