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

_LIBELLE_SOURCE_AIR = {
    "calcul_3cl": "Calcul 3CL-DPE (Hvent + Hperm)",
    "reference_xml": "Référence XML (repli)",
    "indisponible": "Indisponible",
}


def synthetiser(
    h_par_categorie: dict[str, float],
    dr_w_k: float | None = None,
    source_air: str = "indisponible",
) -> pd.DataFrame:
    """Total par poste, part dans GV, unité W/K et source de calcul."""
    total_transmission = sum(h_par_categorie.get(cle, 0.0) for cle, _, _ in CATEGORIES)
    total = total_transmission + (dr_w_k if dr_w_k is not None else 0.0)

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
                "source": "Calcul 3CL-DPE",
            }
        )

    if dr_w_k is not None:
        part_air = 0.0 if total == 0 else 100.0 * dr_w_k / total
        lignes.append(
            {
                "categorie": "Renouvellement d'air",
                "deperdition_w_k": float(dr_w_k),
                "part_pct": part_air,
                "unite": "W/K",
                "source": _LIBELLE_SOURCE_AIR.get(source_air, source_air),
            }
        )

    libelle_total = (
        "Enveloppe globale GV (parois + ponts + air)"
        if dr_w_k is not None
        else "Enveloppe (parois + ponts)"
    )
    lignes.append(
        {
            "categorie": libelle_total,
            "deperdition_w_k": total,
            "part_pct": 100.0 if total else 0.0,
            "unite": "W/K",
            "source": "Total",
        }
    )
    return pd.DataFrame(lignes)


def comparer(
    h_par_categorie: dict[str, float],
    officiel: DeperditionOfficielle,
    dr_w_k: float | None = None,
    air_calcule: bool = False,
) -> pd.DataFrame:
    """Compare chaque poste calculé aux balises ``deperdition_*`` de ``<sortie>``."""
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

    air_officiel = officiel.valeur("deperdition_renouvellement_air")
    if air_calcule and dr_w_k is not None:
        lignes.append(
            _ligne(
                "Renouvellement d'air",
                dr_w_k,
                air_officiel,
                "balise deperdition_renouvellement_air (DR = Hvent + Hperm)",
            )
        )
    else:
        lignes.append(
            _ligne(
                "Renouvellement d'air",
                None,
                air_officiel,
                "non recalculé — valeur de référence XML utilisée en repli",
            )
        )

    enveloppe_xml = officiel.valeur("deperdition_enveloppe")
    if air_calcule and dr_w_k is not None:
        gv_reconstitue = total_calcule + dr_w_k
        commentaire_gv = "transmission calculée + renouvellement d'air calculé (3CL-DPE)"
    elif air_officiel is not None:
        gv_reconstitue = total_calcule + air_officiel
        commentaire_gv = (
            "transmission calculée + renouvellement d'air officiel (repli XML)"
        )
    else:
        gv_reconstitue = None
        commentaire_gv = "renouvellement d'air indisponible pour reconstituer GV"

    lignes.append(
        _ligne(
            "Déperdition enveloppe XML",
            gv_reconstitue,
            enveloppe_xml,
            commentaire_gv,
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