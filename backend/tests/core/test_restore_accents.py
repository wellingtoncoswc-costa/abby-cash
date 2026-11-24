from app.core.text import restore_accents


def test_restores_dropped_accented_letter_from_the_message():
    assert restore_accents("imvel", "cadastrar consórcio do imóvel") == "imóvel"
    assert (
        restore_accents("reserva de emergncia", "criar caixinha reserva de emergência a 120%")
        == "reserva de emergência"
    )


def test_leaves_values_alone_when_nothing_matches():
    assert restore_accents("mercado", "gastei 45 no mercado") == "mercado"  # já está no texto
    assert (
        restore_accents("Padaria", "gastei 45 na padaria") == "Padaria"
    )  # sem acento: não reescreve
    assert restore_accents("viagem", "guardei 50 na reserva") == "viagem"  # nada parecido
    assert restore_accents(None, "x") is None and restore_accents("", "x") == ""
