"""
Motor de análise, em duas camadas:

1) ESTATÍSTICAS: funções que só calculam números reais (forma, gols,
   over/under, BTTS, escanteios, cartões, confrontos) — sem opinião.

2) INTERPRETAÇÃO: pega esses números e estima uma probabilidade PRÓPRIA
   (0-100%) pra cada mercado, baseada só nos dados — nunca na odd do
   mercado. "Alta/Média/Baixa confiança" reflete o quanto essa
   probabilidade se afasta de 50% (uma "moeda honesta", sem favorito
   claro). As odds continuam aparecendo, só como referência pra apostar,
   não influenciam o cálculo.

Observação sobre xG: o endpoint da API-Football usado aqui
(/teams/statistics) não fornece Expected Goals no plano atual. Por
honestidade, não estimamos esse número — se um dia a API passar a
fornecer, é só adicionar.
"""


# ============ CAMADA 1: ESTATÍSTICAS ============

def _forma_em_pontos(form_string: str, ultimos: int = 5) -> int:
    if not form_string:
        return 0
    recorte = form_string[-ultimos:]
    pontos = {"W": 3, "D": 1, "L": 0}
    return sum(pontos.get(c, 0) for c in recorte)


def _pct(numerador, denominador):
    if not denominador:
        return 0
    return (numerador / denominador) * 100


def _clamp(valor, minimo=0, maximo=100):
    return max(minimo, min(valor, maximo))


def _fator_amostra(*contagens_jogos, minimo=5):
    """Reduz a confiança quando o recorte de jogos é pequeno (ex: só 1 jogo fora de casa)."""
    n = min(contagens_jogos) if contagens_jogos else minimo
    return max(0.2, min(n, minimo) / minimo)


def _soma_cartoes_temporada(stats: dict) -> int:
    total = 0
    for tipo in ["yellow", "red"]:
        buckets = stats.get("cards", {}).get(tipo, {})
        for info in buckets.values():
            valor = (info or {}).get("total")
            if valor:
                total += valor
    return total


def _pct_gols_primeiro_tempo(distribuicao_por_minuto: dict) -> float:
    total = 0.0
    for faixa in ["0-15", "16-30", "31-45"]:
        info = distribuicao_por_minuto.get(faixa) or {}
        valor = info.get("percentage")
        if valor:
            total += float(str(valor).replace("%", ""))
    return total


def extrair_odd(odds_response: list, nomes_mercado: list, nome_valor: str):
    """Só pra referência visual — nunca usada no cálculo de confiança."""
    if not odds_response:
        return None
    for entrada in odds_response:
        for bookmaker in entrada.get("bookmakers", []):
            for bet in bookmaker.get("bets", []):
                if bet.get("name") in nomes_mercado:
                    for valor in bet.get("values", []):
                        if valor.get("value") == nome_valor:
                            return valor.get("odd")
    return None


def resumir_h2h(h2h_lista: list, casa_id: int):
    """Resume os confrontos diretos do ponto de vista de quem é mandante HOJE."""
    vitorias_casa_atual = vitorias_fora_atual = empates = 0
    for jogo in h2h_lista or []:
        gols_home = jogo["goals"]["home"]
        gols_away = jogo["goals"]["away"]
        if gols_home is None or gols_away is None:
            continue
        home_desse_jogo = jogo["teams"]["home"]["id"]
        if home_desse_jogo == casa_id:
            gols_casa_atual, gols_fora_atual = gols_home, gols_away
        else:
            gols_casa_atual, gols_fora_atual = gols_away, gols_home
        if gols_casa_atual > gols_fora_atual:
            vitorias_casa_atual += 1
        elif gols_casa_atual < gols_fora_atual:
            vitorias_fora_atual += 1
        else:
            empates += 1
    return {
        "jogos": len(h2h_lista or []),
        "vitorias_casa_atual": vitorias_casa_atual,
        "vitorias_fora_atual": vitorias_fora_atual,
        "empates": empates,
    }


def montar_contexto_lesoes(lesoes_lista, casa_id, fora_id, home_nome, away_nome) -> str:
    nomes_casa, nomes_fora = [], []
    for item in lesoes_lista or []:
        jogador = item.get("player", {}).get("name")
        time_id = item.get("team", {}).get("id")
        if not jogador:
            continue
        if time_id == casa_id:
            nomes_casa.append(jogador)
        elif time_id == fora_id:
            nomes_fora.append(jogador)
    if not nomes_casa and not nomes_fora:
        return "Sem desfalques relevantes registrados para nenhum dos dois lados."
    partes = []
    if nomes_casa:
        partes.append(f"{home_nome} desfalcado de: {', '.join(nomes_casa[:5])}.")
    if nomes_fora:
        partes.append(f"{away_nome} desfalcado de: {', '.join(nomes_fora[:5])}.")
    return " ".join(partes)


def identificar_padrao_gol_tardio(stats: dict, nome: str):
    distrib = stats.get("goals", {}).get("against", {}).get("minute", {})

    def pct(faixa):
        info = distrib.get(faixa) or {}
        valor = info.get("percentage")
        return float(str(valor).replace("%", "")) if valor else 0.0

    pct_final = pct("76-90") + pct("91-105")
    if pct_final >= 35:
        return f"{nome} concentra {pct_final:.0f}% dos gols que sofre nos minutos finais (76'+)."
    return None


def montar_estatisticas_time(stats: dict) -> dict:
    """
    Consolida, num único lugar, os números-chave de um time: forma, gols,
    força ofensiva/defensiva qualitativa, cartões e clean sheets.
    Essa é a "camada 1" pra um time só.
    """
    jogados_total = stats["fixtures"]["played"]["total"] or 1
    media_marca_casa = float(stats["goals"]["for"]["average"]["home"])
    media_marca_fora = float(stats["goals"]["for"]["average"]["away"])
    media_sofre_casa = float(stats["goals"]["against"]["average"]["home"])
    media_sofre_fora = float(stats["goals"]["against"]["average"]["away"])

    def classificar(media, limite_forte, limite_fraco, inverso=False):
        if inverso:
            if media <= limite_forte:
                return "forte"
            if media >= limite_fraco:
                return "frágil"
            return "mediana"
        if media >= limite_forte:
            return "forte"
        if media <= limite_fraco:
            return "fraco"
        return "mediano"

    return {
        "forma": stats.get("form", ""),
        "pontos_forma": _forma_em_pontos(stats.get("form", "")),
        "media_marca_casa": media_marca_casa,
        "media_marca_fora": media_marca_fora,
        "media_sofre_casa": media_sofre_casa,
        "media_sofre_fora": media_sofre_fora,
        "ataque_qualidade": classificar((media_marca_casa + media_marca_fora) / 2, 1.4, 0.9),
        "defesa_qualidade": classificar((media_sofre_casa + media_sofre_fora) / 2, 0.9, 1.4, inverso=True),
        "media_cartoes": round(_soma_cartoes_temporada(stats) / jogados_total, 2),
        "pct_ht": _pct_gols_primeiro_tempo(stats["goals"]["for"]["minute"]),
    }


def _sequencia_forma(form_string: str, ultimos: int = 5) -> str:
    """Transforma 'WWLDW' (formato da API) em 'V-V-D-E-V' (Vitória/Empate/Derrota)."""
    if not form_string:
        return "sem dados suficientes"
    recorte = form_string[-ultimos:]
    traducao = {"W": "V", "D": "E", "L": "D"}
    return "-".join(traducao.get(c, "?") for c in recorte)


def montar_contexto_forca(home_stats, away_stats, home_nome, away_nome) -> str:
    """Frase de analista resumindo a força ofensiva/defensiva de cada lado, com o retrospecto recente."""
    perfil_casa = montar_estatisticas_time(home_stats)
    perfil_fora = montar_estatisticas_time(away_stats)
    seq_casa = _sequencia_forma(perfil_casa["forma"])
    seq_fora = _sequencia_forma(perfil_fora["forma"])
    return (
        f"{home_nome}: ataque {perfil_casa['ataque_qualidade']}, defesa {perfil_casa['defesa_qualidade']} "
        f"(marca {perfil_casa['media_marca_casa']:.1f}/sofre {perfil_casa['media_sofre_casa']:.1f} em casa). "
        f"Últimos jogos: {seq_casa}. "
        f"{away_nome}: ataque {perfil_fora['ataque_qualidade']}, defesa {perfil_fora['defesa_qualidade']} "
        f"(marca {perfil_fora['media_marca_fora']:.1f}/sofre {perfil_fora['media_sofre_fora']:.1f} fora). "
        f"Últimos jogos: {seq_fora}."
    )


def montar_contexto_avancado(avancadas_casa, avancadas_fora, home_nome, away_nome):
    """Texto com chutes, faltas e escanteios médios, quando disponíveis (opt-in, custa mais requisições)."""
    if not avancadas_casa or not avancadas_fora:
        return None

    def bloco(nome, dados):
        partes = []
        if dados.get("chutes_totais") is not None:
            partes.append(f"{dados['chutes_totais']} chutes ({dados.get('chutes_alvo', '?')} no alvo)")
        if dados.get("faltas_cometidas") is not None:
            partes.append(f"{dados['faltas_cometidas']} faltas cometidas")
        if dados.get("faltas_sofridas") is not None:
            partes.append(f"{dados['faltas_sofridas']} faltas sofridas")
        if dados.get("escanteios") is not None:
            partes.append(f"{dados['escanteios']} escanteios")
        return f"{nome}: " + ", ".join(partes) + " por jogo (média últimos jogos)." if partes else None

    linhas = [bloco(home_nome, avancadas_casa), bloco(away_nome, avancadas_fora)]
    linhas = [l for l in linhas if l]
    return " ".join(linhas) if linhas else None


def montar_tabela_comparativa(home_stats, away_stats, home_nome, away_nome, avancadas_casa=None, avancadas_fora=None):
    """
    Monta os números lado a lado dos dois times: gols marcados/sofridos,
    % de vitória casa/fora, cartões, e (se disponível) chutes/escanteios.
    Devolve uma lista de linhas prontas pra virar tabela na tela.
    """
    jogados_casa = home_stats["fixtures"]["played"]["home"] or 1
    jogados_fora = away_stats["fixtures"]["played"]["away"] or 1
    jogados_casa_total = home_stats["fixtures"]["played"]["total"] or 1
    jogados_fora_total = away_stats["fixtures"]["played"]["total"] or 1

    linhas = [
        {
            "estatistica": "Gols marcados (média)",
            home_nome: f"{float(home_stats['goals']['for']['average']['home']):.1f}",
            away_nome: f"{float(away_stats['goals']['for']['average']['away']):.1f}",
        },
        {
            "estatistica": "Gols sofridos (média)",
            home_nome: f"{float(home_stats['goals']['against']['average']['home']):.1f}",
            away_nome: f"{float(away_stats['goals']['against']['average']['away']):.1f}",
        },
        {
            "estatistica": "% Vitórias (casa/fora)",
            home_nome: f"{_pct(home_stats['fixtures']['wins']['home'], jogados_casa):.0f}%",
            away_nome: f"{_pct(away_stats['fixtures']['wins']['away'], jogados_fora):.0f}%",
        },
        {
            "estatistica": "Cartões recebidos (média)",
            home_nome: f"{_soma_cartoes_temporada(home_stats) / jogados_casa_total:.1f}",
            away_nome: f"{_soma_cartoes_temporada(away_stats) / jogados_fora_total:.1f}",
        },
    ]

    if avancadas_casa and avancadas_fora:
        extras = [
            ("Chutes (média)", "chutes_totais"),
            ("Chutes no alvo (média)", "chutes_alvo"),
            ("Escanteios (média)", "escanteios"),
        ]
        for rotulo, chave in extras:
            linhas.append({
                "estatistica": rotulo,
                home_nome: avancadas_casa.get(chave) if avancadas_casa.get(chave) is not None else "—",
                away_nome: avancadas_fora.get(chave) if avancadas_fora.get(chave) is not None else "—",
            })

    return linhas


# ============ CAMADA 2: INTERPRETAÇÃO ============

def _rotulo_confianca(confianca_pct: float) -> str:
    """Alta/Média/Baixa reflete o quanto a probabilidade estimada se afasta de 50%."""
    distancia = abs(confianca_pct - 50)
    if distancia >= 20:
        return "Alta"
    if distancia >= 10:
        return "Média"
    return "Baixa"


def _analise_resultado(home_stats, away_stats, home_nome, away_nome, odds,
                        standings_casa=None, standings_fora=None, h2h_resumo=None):
    pontos_casa = _forma_em_pontos(home_stats.get("form", ""))
    pontos_fora = _forma_em_pontos(away_stats.get("form", ""))

    jogados_casa = home_stats["fixtures"]["played"]["home"]
    vitorias_casa = home_stats["fixtures"]["wins"]["home"]
    pct_vitoria_casa = _pct(vitorias_casa, jogados_casa)

    jogados_fora = away_stats["fixtures"]["played"]["away"]
    vitorias_fora = away_stats["fixtures"]["wins"]["away"]
    pct_vitoria_fora = _pct(vitorias_fora, jogados_fora)

    combinado_casa = pct_vitoria_casa * 0.5 + (pontos_casa / 15 * 100) * 0.3
    combinado_fora = pct_vitoria_fora * 0.5 + (pontos_fora / 15 * 100) * 0.3

    frases_extras = []

    if standings_casa and standings_fora:
        rank_casa, rank_fora = standings_casa["rank"], standings_fora["rank"]
        nudge = _clamp((rank_fora - rank_casa) * 1.5, -15, 15)
        combinado_casa += max(nudge, 0)
        combinado_fora += max(-nudge, 0)
        frases_extras.append(
            f"Na tabela, o {home_nome} está em {rank_casa}º com {standings_casa['points']} pontos, "
            f"contra {rank_fora}º e {standings_fora['points']} pontos do {away_nome}."
        )

    if h2h_resumo and h2h_resumo["jogos"] > 0:
        saldo = h2h_resumo["vitorias_casa_atual"] - h2h_resumo["vitorias_fora_atual"]
        combinado_casa += max(saldo * 5, 0)
        combinado_fora += max(-saldo * 5, 0)
        frases_extras.append(
            f"Nos últimos {h2h_resumo['jogos']} confrontos diretos, {home_nome} venceu "
            f"{h2h_resumo['vitorias_casa_atual']}, {away_nome} venceu {h2h_resumo['vitorias_fora_atual']} "
            f"e houve {h2h_resumo['empates']} empate(s)."
        )

    for padrao in [identificar_padrao_gol_tardio(home_stats, home_nome), identificar_padrao_gol_tardio(away_stats, away_nome)]:
        if padrao:
            frases_extras.append(padrao)

    diferenca = combinado_casa - combinado_fora
    raw_prob_favorito = _clamp(50 + diferenca / 2, 30, 90)

    if diferenca >= 20:
        escolha, mercado_odd, valor_odd, prob_final = f"Vitória {home_nome}", "Match Winner", "Home", raw_prob_favorito
    elif diferenca >= 8:
        escolha, mercado_odd, valor_odd, prob_final = f"Dupla Chance ({home_nome} ou Empate)", "Double Chance", "Home/Draw", raw_prob_favorito
    elif diferenca <= -20:
        escolha, mercado_odd, valor_odd, prob_final = f"Vitória {away_nome}", "Match Winner", "Away", raw_prob_favorito
    elif diferenca <= -8:
        escolha, mercado_odd, valor_odd, prob_final = f"Dupla Chance ({away_nome} ou Empate)", "Double Chance", "Draw/Away", raw_prob_favorito
    else:
        escolha, mercado_odd, valor_odd, prob_final = "Empate", "Match Winner", "Draw", 50

    odd = extrair_odd(odds, [mercado_odd], valor_odd)

    narrativa = (
        f"O {home_nome} chega com {pontos_casa} pontos nos últimos jogos e venceu {vitorias_casa} de "
        f"{jogados_casa} como mandante ({pct_vitoria_casa:.0f}% em casa). O {away_nome} soma {pontos_fora} "
        f"pontos no mesmo recorte e venceu {vitorias_fora} de {jogados_fora} como visitante ({pct_vitoria_fora:.0f}% fora). "
    )
    narrativa += " ".join(frases_extras)

    fator = _fator_amostra(jogados_casa, jogados_fora)
    confianca_pct = round(50 + (prob_final - 50) * fator, 1)
    if fator < 0.6:
        narrativa += f" (Amostra pequena — {min(jogados_casa, jogados_fora)} jogo(s), confiança reduzida.)"

    return {
        "mercado": "Resultado", "escolha": escolha, "odd": odd, "narrativa": narrativa.strip(),
        "confianca_pct": confianca_pct,
    }


def _analise_gols(home_stats, away_stats, home_nome, away_nome, odds, linha=2.5):
    media_casa_marca = float(home_stats["goals"]["for"]["average"]["home"])
    media_fora_marca = float(away_stats["goals"]["for"]["average"]["away"])
    media_casa_sofre = float(home_stats["goals"]["against"]["average"]["home"])
    media_fora_sofre = float(away_stats["goals"]["against"]["average"]["away"])
    jogados_casa = home_stats["fixtures"]["played"]["home"]
    jogados_fora = away_stats["fixtures"]["played"]["away"]

    expectativa_gols = media_casa_marca + media_fora_marca
    raw_prob_over = _clamp(50 + (expectativa_gols - linha) * 20, 10, 90)

    if raw_prob_over >= 50:
        escolha, valor_odd, prob_final = f"Mais de {linha} gols", f"Over {linha}", raw_prob_over
    else:
        escolha, valor_odd, prob_final = f"Menos de {linha} gols", f"Under {linha}", 100 - raw_prob_over

    odd = extrair_odd(odds, ["Goals Over/Under"], valor_odd)

    narrativa = (
        f"O {home_nome} marca em média {media_casa_marca:.1f} gols em casa e sofre {media_casa_sofre:.1f}. "
        f"O {away_nome} marca {media_fora_marca:.1f} fora e sofre {media_fora_sofre:.1f}. "
        f"Expectativa de {expectativa_gols:.1f} gols na partida."
    )

    fator = _fator_amostra(jogados_casa, jogados_fora)
    confianca_pct = round(50 + (prob_final - 50) * fator, 1)
    if fator < 0.6:
        narrativa += f" (Amostra pequena — {min(jogados_casa, jogados_fora)} jogo(s), confiança reduzida.)"

    return {
        "mercado": "Total de Gols", "escolha": escolha, "odd": odd, "narrativa": narrativa,
        "confianca_pct": confianca_pct,
    }


def _analise_btts(home_stats, away_stats, home_nome, away_nome, odds):
    media_casa_marca = float(home_stats["goals"]["for"]["average"]["home"])
    media_casa_sofre = float(home_stats["goals"]["against"]["average"]["home"])
    media_fora_marca = float(away_stats["goals"]["for"]["average"]["away"])
    media_fora_sofre = float(away_stats["goals"]["against"]["average"]["away"])
    jogados_casa = home_stats["fixtures"]["played"]["home"]
    jogados_fora = away_stats["fixtures"]["played"]["away"]

    indicador = (media_casa_marca - 1) + (media_fora_marca - 1) + (media_casa_sofre - 1) * 0.5 + (media_fora_sofre - 1) * 0.5
    raw_prob_sim = _clamp(50 + indicador * 15, 10, 90)

    if raw_prob_sim >= 50:
        escolha, valor_odd, prob_final = "Ambas Marcam - Sim", "Yes", raw_prob_sim
    else:
        escolha, valor_odd, prob_final = "Ambas Marcam - Não", "No", 100 - raw_prob_sim

    odd = extrair_odd(odds, ["Both Teams Score", "Both Teams To Score"], valor_odd)

    narrativa = (
        f"Em casa, o {home_nome} marca {media_casa_marca:.1f} e sofre {media_casa_sofre:.1f} por jogo. "
        f"Fora, o {away_nome} marca {media_fora_marca:.1f} e sofre {media_fora_sofre:.1f}."
    )

    fator = _fator_amostra(jogados_casa, jogados_fora)
    confianca_pct = round(50 + (prob_final - 50) * fator, 1)
    if fator < 0.6:
        narrativa += f" (Amostra pequena — {min(jogados_casa, jogados_fora)} jogo(s), confiança reduzida.)"

    return {
        "mercado": "Ambas Marcam", "escolha": escolha, "odd": odd, "narrativa": narrativa,
        "confianca_pct": confianca_pct,
    }


def _analise_gols_primeiro_tempo(home_stats, away_stats, home_nome, away_nome, odds):
    media_casa_marca = float(home_stats["goals"]["for"]["average"]["home"])
    media_fora_marca = float(away_stats["goals"]["for"]["average"]["away"])
    expectativa_gols = media_casa_marca + media_fora_marca
    jogados_casa = home_stats["fixtures"]["played"]["home"]
    jogados_fora = away_stats["fixtures"]["played"]["away"]

    pct_casa_ht = _pct_gols_primeiro_tempo(home_stats["goals"]["for"]["minute"])
    pct_fora_ht = _pct_gols_primeiro_tempo(away_stats["goals"]["for"]["minute"])
    media_pct_ht = (pct_casa_ht + pct_fora_ht) / 2 if (pct_casa_ht or pct_fora_ht) else 45.0
    expectativa_ht = expectativa_gols * (media_pct_ht / 100)

    raw_prob_over = _clamp(50 + (expectativa_ht - 0.5) * 40, 10, 90)
    if raw_prob_over >= 50:
        escolha, valor_odd, prob_final = "Mais de 0.5 gols no 1º tempo", "Over 0.5", raw_prob_over
    else:
        escolha, valor_odd, prob_final = "Menos de 0.5 gols no 1º tempo", "Under 0.5", 100 - raw_prob_over

    odd = extrair_odd(odds, ["Goals Over/Under First Half"], valor_odd)

    narrativa = (
        f"Historicamente, {pct_casa_ht:.0f}% dos gols do {home_nome} e {pct_fora_ht:.0f}% dos gols do "
        f"{away_nome} saem no 1º tempo. Projeção pro primeiro tempo: {expectativa_ht:.1f} gols."
    )

    fator = _fator_amostra(jogados_casa, jogados_fora)
    confianca_pct = round(50 + (prob_final - 50) * fator, 1)

    return {
        "mercado": "Gols no 1º Tempo", "escolha": escolha, "odd": odd, "narrativa": narrativa,
        "confianca_pct": confianca_pct,
    }


def _analise_clean_sheet(home_stats, away_stats, home_nome, away_nome, odds):
    jogados_casa = home_stats["fixtures"]["played"]["home"]
    jogados_fora = away_stats["fixtures"]["played"]["away"]

    home_clean_pct = _pct(home_stats.get("clean_sheet", {}).get("home", 0), jogados_casa)
    away_failed_pct = _pct(away_stats.get("failed_to_score", {}).get("away", 0), jogados_fora)
    away_clean_pct = _pct(away_stats.get("clean_sheet", {}).get("away", 0), jogados_fora)
    home_failed_pct = _pct(home_stats.get("failed_to_score", {}).get("home", 0), jogados_casa)

    score_casa_zera = (home_clean_pct + away_failed_pct) / 2
    score_fora_zera = (away_clean_pct + home_failed_pct) / 2

    if score_casa_zera >= score_fora_zera:
        time_favorito, contra, pct_favoravel, pct_contra, raw_prob = home_nome, away_nome, home_clean_pct, away_failed_pct, score_casa_zera
    else:
        time_favorito, contra, pct_favoravel, pct_contra, raw_prob = away_nome, home_nome, away_clean_pct, home_failed_pct, score_fora_zera

    escolha = f"{time_favorito} não sofre gol (Clean Sheet)"
    odd = extrair_odd(odds, ["Team Clean Sheet", "Home Team Clean Sheet", "Away Team Clean Sheet"], "Yes")

    narrativa = (
        f"O {time_favorito} não sofreu gol em {pct_favoravel:.0f}% dos jogos nesse recorte, "
        f"e o {contra} não marcou em {pct_contra:.0f}% dos seus jogos no mesmo período."
    )

    fator = _fator_amostra(jogados_casa, jogados_fora)
    prob_final = _clamp(raw_prob, 10, 90)
    confianca_pct = round(50 + (prob_final - 50) * fator, 1)
    if fator < 0.6:
        narrativa += f" (Amostra pequena — {min(jogados_casa, jogados_fora)} jogo(s), confiança reduzida.)"

    return {
        "mercado": "Clean Sheet", "escolha": escolha, "odd": odd, "narrativa": narrativa,
        "confianca_pct": confianca_pct,
    }


def _analise_escanteios(escanteios_casa, escanteios_fora, home_nome, away_nome, odds):
    if escanteios_casa is None or escanteios_fora is None:
        raise ValueError("Sem dados suficientes de escanteios")

    expectativa = escanteios_casa + escanteios_fora
    raw_prob_over = _clamp(50 + (expectativa - 8.5) * 8, 10, 90)
    if raw_prob_over >= 50:
        escolha, valor_odd, prob_final = "Mais de 8.5 escanteios", "Over 8.5", raw_prob_over
    else:
        escolha, valor_odd, prob_final = "Menos de 8.5 escanteios", "Under 8.5", 100 - raw_prob_over

    odd = extrair_odd(odds, ["Corners Over Under", "Corner Over Under", "Total Corners"], valor_odd)

    narrativa = (
        f"O {home_nome} teve média de {escanteios_casa:.1f} escanteios por partida e o {away_nome} "
        f"teve {escanteios_fora:.1f}. Expectativa de {expectativa:.1f} escanteios no confronto."
    )

    return {
        "mercado": "Escanteios", "escolha": escolha, "odd": odd, "narrativa": narrativa,
        "confianca_pct": round(prob_final, 1),
    }


def _analise_cartoes(home_stats, away_stats, home_nome, away_nome, odds):
    jogados_casa_total = home_stats["fixtures"]["played"]["total"] or 1
    jogados_fora_total = away_stats["fixtures"]["played"]["total"] or 1

    media_cartoes_casa = _soma_cartoes_temporada(home_stats) / jogados_casa_total
    media_cartoes_fora = _soma_cartoes_temporada(away_stats) / jogados_fora_total
    expectativa = media_cartoes_casa + media_cartoes_fora

    raw_prob_over = _clamp(50 + (expectativa - 4.5) * 15, 10, 90)
    if raw_prob_over >= 50:
        escolha, valor_odd, prob_final = "Mais de 4.5 cartões", "Over 4.5", raw_prob_over
    else:
        escolha, valor_odd, prob_final = "Menos de 4.5 cartões", "Under 4.5", 100 - raw_prob_over

    odd = extrair_odd(odds, ["Cards Over/Under", "Total Cards"], valor_odd)

    narrativa = (
        f"O {home_nome} recebe em média {media_cartoes_casa:.1f} cartões por jogo na temporada, e o "
        f"{away_nome} recebe {media_cartoes_fora:.1f}. Expectativa de {expectativa:.1f} cartões no confronto."
    )

    fator = _fator_amostra(jogados_casa_total, jogados_fora_total)
    confianca_pct = round(50 + (prob_final - 50) * fator, 1)

    return {
        "mercado": "Cartões", "escolha": escolha, "odd": odd, "narrativa": narrativa,
        "confianca_pct": confianca_pct,
    }


def gerar_dicas_do_jogo(home_stats, away_stats, home_nome, away_nome, odds,
                         standings_casa=None, standings_fora=None, h2h_resumo=None,
                         escanteios_casa=None, escanteios_fora=None):
    """
    Gera até 7 candidatos de mercado (cada um com sua PRÓPRIA probabilidade
    estimada a partir dos dados) e devolve os 3 mais distantes de 50%
    (ou seja, os 3 em que os números realmente apontam um lado, e não
    um "quase empate estatístico"). Alta/Média/Baixa reflete a distância
    de 50% de cada dica individualmente — não a posição entre as 3.
    """
    candidatos = []
    tentativas = [
        lambda: _analise_resultado(home_stats, away_stats, home_nome, away_nome, odds, standings_casa, standings_fora, h2h_resumo),
        lambda: _analise_gols(home_stats, away_stats, home_nome, away_nome, odds),
        lambda: _analise_btts(home_stats, away_stats, home_nome, away_nome, odds),
        lambda: _analise_gols_primeiro_tempo(home_stats, away_stats, home_nome, away_nome, odds),
        lambda: _analise_clean_sheet(home_stats, away_stats, home_nome, away_nome, odds),
        lambda: _analise_cartoes(home_stats, away_stats, home_nome, away_nome, odds),
        lambda: _analise_escanteios(escanteios_casa, escanteios_fora, home_nome, away_nome, odds),
    ]

    for tentar in tentativas:
        try:
            candidatos.append(tentar())
        except (KeyError, TypeError, ValueError):
            continue

    # "Ambas Marcam - Sim" e "Clean Sheet" são logicamente incompatíveis.
    btts_c = next((c for c in candidatos if c["mercado"] == "Ambas Marcam"), None)
    clean_c = next((c for c in candidatos if c["mercado"] == "Clean Sheet"), None)
    if btts_c and clean_c and btts_c["escolha"] == "Ambas Marcam - Sim":
        perdedor = min([btts_c, clean_c], key=lambda c: abs(c["confianca_pct"] - 50))
        candidatos.remove(perdedor)

    # Ranqueia pela distância de 50% (quanto mais longe do "empate estatístico", melhor a dica)
    escolhidos = sorted(candidatos, key=lambda c: abs(c["confianca_pct"] - 50), reverse=True)[:3]

    for dica in escolhidos:
        dica["confianca"] = _rotulo_confianca(dica["confianca_pct"])

    return escolhidos
