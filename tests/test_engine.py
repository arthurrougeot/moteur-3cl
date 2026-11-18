"""Tests du moteur contre les valeurs de référence du XML ADEME d'exemple."""
from pathlib import Path

import pytest

from calculator import calculer_enveloppe
from parser import BaieVitree, PlancherBas, parse_dpe

XML = Path(__file__).resolve().parent.parent / "data" / "2671E0055558U.xml"

# Écart toléré : upb_final est publié arrondi à 5 décimales dans le XML.
TOLERANCE_W_K = 1e-3


@pytest.fixture(scope="module")
def dpe():
    return parse_dpe(XML)


@pytest.fixture(scope="module")
def resultat(dpe):
    return calculer_enveloppe(dpe)


@pytest.mark.parametrize(
    "categorie, balise",
    [
        ("murs", "deperdition_mur"),
        ("planchers_bas", "deperdition_plancher_bas"),
        ("planchers_hauts", "deperdition_plancher_haut"),
        ("baies", "deperdition_baie_vitree"),
        ("portes", "deperdition_porte"),
        ("ponts_thermiques", "deperdition_pont_thermique"),
    ],
)
def test_chaque_poste_retrouve_la_reference(dpe, resultat, categorie, balise):
    reference = dpe.deperdition.valeur(balise)
    assert reference is not None
    assert resultat.h_par_categorie[categorie] == pytest.approx(
        reference, abs=TOLERANCE_W_K
    )


def test_total_enveloppe_contre_xml(dpe, resultat):
    """deperdition_enveloppe du XML = transmission + renouvellement d'air."""
    air = dpe.deperdition.valeur("deperdition_renouvellement_air")
    enveloppe = dpe.deperdition.valeur("deperdition_enveloppe")
    assert resultat.h_enveloppe + air == pytest.approx(enveloppe, abs=TOLERANCE_W_K)


def test_mur_calcul_a_la_main():
    from calculator import calculer_murs
    from parser import Mur

    cadre = calculer_murs([Mur(description="m", surface_paroi_opaque=10.0, umur=2.0, b=0.5)])
    assert cadre.loc[0, "deperdition_w_k"] == pytest.approx(10.0)


def test_baie_sans_ujn_utilise_uw():
    baie = BaieVitree(description="f", surface_totale_baie=2.0, uw=2.4)
    assert baie.coefficient_u() == (2.4, "uw")


def test_plancher_bas_sans_upb_final_utilise_upb():
    plancher = PlancherBas(description="p", surface_paroi_opaque=1.0, upb=0.5)
    assert plancher.coefficient_u() == (0.5, "upb")


def test_b_nul_conserve():
    from calculator import calculer_murs
    from parser import Mur

    cadre = calculer_murs([Mur(description="m", surface_paroi_opaque=10.0, umur=2.0, b=0.0)])
    assert cadre.loc[0, "deperdition_w_k"] == 0.0
