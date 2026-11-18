"""Synthèse des déperditions et comparaison aux valeurs ``<sortie>``."""
from __future__ import annotations
import math
import pandas as pd
from parser import DeperditionOfficielle
CATEGORIES = (
    ("murs", "Murs", "deperdition_mur"),
    ("planchers_bas", "Planchers bas", "deperdition_plancher_bas"),
    ("planchers_hauts", "Planchers hauts", "deperdition_plancher_haut"),
    ("baies", "Baies vitrées", "deperdition_baie_vitree"),
    ("portes", "Portes", "deperdition_porte"),
    ("ponts_thermiques", "Ponts thermiques", "deperdition_pont_thermique"),
)
# En dessous de ce seuil, l'écart est un arrondi de coefficient publié
# (upb à 5 décimales, par exemple), pas une différence de formule.
SEUIL_ARRONDI_W_K = 1e-2
def synthetiser(h_par_categorie: dict[str, float]) -> pd.DataFrame:
    """Total par poste, part dans H_enveloppe, unité W/K.
    Les parts sont calculées sur l'enveloppe de transmission
    (parois + ponts), sans le renouvellement d'air.
    """
    total = sum(h_par_categorie.get(cle, 0.0) for cle, _, _ in CATEGORIES)
    lignes = []
    for cle, libelle, _ in CATEGORIES:
        valeur = float(h_par_categorie.get(cle, 0.0))
        part = 0.0 if total == 0 else 100.0 * valeur / total
        lignes.append(
            {
                "categorie": libelle,
                "deperdition_w_k": valeur,
                "part_pct": part,
                "unite": "W/K",
            }
        )
    lignes.append(
        {
            "categorie": "Enveloppe (parois + ponts)",
            "deperdition_w_k": total,
            "part_pct": 100.0 if total else 0.0,
            "unite": "W/K",
        }
    )
    return pd.DataFrame(lignes)
def comparer(
    h_par_categorie: dict[str, float],
    officiel: DeperditionOfficielle,
) -> pd.DataFrame:
    """Calculé contre les balises ``deperdition_*`` de ``<sortie>``.
    La dernière ligne reconstitue ``deperdition_enveloppe`` en ajoutant
    le renouvellement d'air officiel, qui n'est pas recalculé ici.
    """
    lignes = []
    total_calcule = 0.0
    total_officiel_transmission = 0.0
    transmission_complete = True
    for cle, libelle, balise in CATEGORIES:
        calcule = float(h_par_categorie.get(cle, 0.0))
        reference = officiel.valeur(balise)
        total_calcule += calcule
        if reference is None:
            transmission_complete = False
        else:
            total_officiel_transmission += reference
        lignes.append(_ligne(libelle, calcule, reference, f"balise {balise}"))
    lignes.append(
        _ligne(
            "Enveloppe transmission (parois + ponts)",
            total_calcule,
            total_officiel_transmission if transmission_complete else None,
            "somme des balises deperdition de transmission",
        )
    )
    air = officiel.valeur("deperdition_renouvellement_air")
    lignes.append(
        _ligne(
            "Renouvellement d'air",
            None,
            air,
            "hors périmètre — non recalculé (hvent + hperm)",
        )
    )
    enveloppe_xml = officiel.valeur("deperdition_enveloppe")
    calcule_reconstitue = None if air is None else total_calcule + air
    lignes.append(
        _ligne(
            "Déperdition enveloppe XML",
            calcule_reconstitue,
            enveloppe_xml,
            "transmission calculée + renouvellement d'air officiel. "
            "deperdition_enveloppe ADEME inclut l'air.",
        )
    )
    return pd.DataFrame(lignes)
def _ligne(
    categorie: str,
    calcule: float | None,
    officiel: float | None,
    commentaire: str,
) -> dict:
    ecart = None
    ecart_pct = None
    if calcule is not None and officiel is not None:
        ecart = calcule - officiel
        if officiel != 0:
            ecart_pct = 100.0 * ecart / officiel
        commentaire = _qualifier(ecart, commentaire)
    elif calcule is None and officiel is not None:
        commentaire = commentaire
    return {
        "categorie": categorie,
        "calcule_w_k": calcule,
        "officiel_w_k": officiel,
        "ecart_w_k": ecart,
        "ecart_relatif_pct": ecart_pct,
        "commentaire": commentaire,
    }


def _qualifier(ecart: float, commentaire: str) -> str:
    """Ajoute un verdict lisible au commentaire."""
    if math.isclose(ecart, 0.0, abs_tol=1e-9):
        return f"{commentaire} — identique"
    if abs(ecart) < SEUIL_ARRONDI_W_K:
        return f"{commentaire} — écart d'arrondi"
    return f"{commentaire} — ÉCART À EXPLIQUER"
