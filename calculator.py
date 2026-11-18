"""Déperditions statiques de l'enveloppe, méthode 3CL-DPE.
H_enveloppe = Σ H_murs + Σ H_planchers_bas + Σ H_planchers_hauts
            + Σ H_baies + Σ H_portes + Σ H_ponts_thermiques
Le renouvellement d'air (hvent + hperm) n'entre pas dans cette somme.
Dans le XML ADEME il est inclus dans ``deperdition_enveloppe``.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from parser import (
    BaieVitree,
    Dpe,
    Mur,
    PlancherBas,
    PlancherHaut,
    PontThermique,
    Porte,
)
from report import comparer, synthetiser
COLONNES_PAROI = [
    "description",
    "surface_m2",
    "u_w_m2k",
    "b",
    "deperdition_w_k",
    "formule",
    "reference",
    "source_u",
]
COLONNES_PONT = [
    "description",
    "longueur_m",
    "k_w_mk",
    "pourcentage",
    "b",
    "deperdition_w_k",
    "formule",
    "reference",
]
@dataclass
class ResultatCalcul:
    details: dict[str, pd.DataFrame]
    synthese: pd.DataFrame
    comparaison: pd.DataFrame
    h_par_categorie: dict[str, float]
    h_enveloppe: float
def calculer_enveloppe(dpe: Dpe) -> ResultatCalcul:
    details = {
        "murs": calculer_murs(dpe.murs),
        "planchers_bas": calculer_planchers_bas(dpe.planchers_bas),
        "planchers_hauts": calculer_planchers_hauts(dpe.planchers_hauts),
        "baies": calculer_baies(dpe.baies),
        "portes": calculer_portes(dpe.portes),
        "ponts_thermiques": calculer_ponts_thermiques(dpe.ponts_thermiques),
    }
    h_par_categorie = {
        cle: float(cadre["deperdition_w_k"].sum()) if not cadre.empty else 0.0
        for cle, cadre in details.items()
    }
    return ResultatCalcul(
        details=details,
        synthese=synthetiser(h_par_categorie),
        comparaison=comparer(h_par_categorie, dpe.deperdition),
        h_par_categorie=h_par_categorie,
        h_enveloppe=sum(h_par_categorie.values()),
    )
def calculer_murs(murs: list[Mur]) -> pd.DataFrame:
    """H_mur = surface_paroi_opaque × umur × b."""
    lignes = []
    for mur in murs:
        deperdition = mur.surface_paroi_opaque * mur.umur * mur.b
        lignes.append(
            {
                "description": mur.description,
                "surface_m2": mur.surface_paroi_opaque,
                "u_w_m2k": mur.umur,
                "b": mur.b,
                "deperdition_w_k": deperdition,
                "formule": (
                    "H = surface_paroi_opaque * umur * b = "
                    f"{_n(mur.surface_paroi_opaque)} * {_n(mur.umur)} * {_n(mur.b)}"
                ),
                "reference": mur.reference,
                "source_u": "umur",
            }
        )
    return _cadre(lignes, COLONNES_PAROI)
def calculer_planchers_bas(planchers: list[PlancherBas]) -> pd.DataFrame:
    """H = surface_paroi_opaque × upb_final × b, sinon upb."""
    lignes = []
    for plancher in planchers:
        u, source = plancher.coefficient_u()
        deperdition = plancher.surface_paroi_opaque * u * plancher.b
        secours = "" if source == "upb_final" else " (upb_final absent)"
        lignes.append(
            {
                "description": plancher.description,
                "surface_m2": plancher.surface_paroi_opaque,
                "u_w_m2k": u,
                "b": plancher.b,
                "deperdition_w_k": deperdition,
                "formule": (
                    f"H = surface_paroi_opaque * {source} * b = "
                    f"{_n(plancher.surface_paroi_opaque)} * {_n(u)} * {_n(plancher.b)}"
                    f"{secours}"
                ),
                "reference": plancher.reference,
                "source_u": source,
            }
        )
    return _cadre(lignes, COLONNES_PAROI)
def calculer_planchers_hauts(planchers: list[PlancherHaut]) -> pd.DataFrame:
    """H_plancher_haut = surface_paroi_opaque × uph × b."""
    lignes = []
    for plancher in planchers:
        deperdition = plancher.surface_paroi_opaque * plancher.uph * plancher.b
        lignes.append(
            {
                "description": plancher.description,
                "surface_m2": plancher.surface_paroi_opaque,
                "u_w_m2k": plancher.uph,
                "b": plancher.b,
                "deperdition_w_k": deperdition,
                "formule": (
                    "H = surface_paroi_opaque * uph * b = "
                    f"{_n(plancher.surface_paroi_opaque)} * {_n(plancher.uph)} * {_n(plancher.b)}"
                ),
                "reference": plancher.reference,
                "source_u": "uph",
            }
        )
    return _cadre(lignes, COLONNES_PAROI)


def calculer_baies(baies: list[BaieVitree]) -> pd.DataFrame:
    """H_baie = surface_totale_baie × ujn × b, sinon uw si ujn est absent."""
    lignes = []
    for baie in baies:
        u, source = baie.coefficient_u()
        deperdition = baie.surface_totale_baie * u * baie.b
        secours = "" if source == "ujn" else " (ujn absent : pas de fermeture)"
        lignes.append(
            {
                "description": baie.description,
                "surface_m2": baie.surface_totale_baie,
                "u_w_m2k": u,
                "b": baie.b,
                "deperdition_w_k": deperdition,
                "formule": (
                    f"H = surface_totale_baie * {source} * b = "
                    f"{_n(baie.surface_totale_baie)} * {_n(u)} * {_n(baie.b)}"
                    f"{secours}"
                ),
                "reference": baie.reference,
                "source_u": source,
            }
        )
    return _cadre(lignes, COLONNES_PAROI)


def calculer_portes(portes: list[Porte]) -> pd.DataFrame:
    """H_porte = surface_porte × uporte × b."""
    lignes = []
    for porte in portes:
        deperdition = porte.surface_porte * porte.uporte * porte.b
        lignes.append(
            {
                "description": porte.description,
                "surface_m2": porte.surface_porte,
                "u_w_m2k": porte.uporte,
                "b": porte.b,
                "deperdition_w_k": deperdition,
                "formule": (
                    "H = surface_porte * uporte * b = "
                    f"{_n(porte.surface_porte)} * {_n(porte.uporte)} * {_n(porte.b)}"
                ),
                "reference": porte.reference,
                "source_u": "uporte",
            }
        )
    return _cadre(lignes, COLONNES_PAROI)


def calculer_ponts_thermiques(ponts: list[PontThermique]) -> pd.DataFrame:
    """H_pont = k × l × pourcentage_valeur_pont_thermique × b (k en W/m.K, l en m)."""
    lignes = []
    for pont in ponts:
        deperdition = pont.k * pont.longueur_m * pont.pourcentage * pont.b
        lignes.append(
            {
                "description": pont.description,
                "longueur_m": pont.longueur_m,
                "k_w_mk": pont.k,
                "pourcentage": pont.pourcentage,
                "b": pont.b,
                "deperdition_w_k": deperdition,
                "formule": (
                    "H = k * l * pourcentage * b = "
                    f"{_n(pont.k)} * {_n(pont.longueur_m)} * "
                    f"{_n(pont.pourcentage)} * {_n(pont.b)}"
                ),
                "reference": pont.reference,
            }
        )
    return _cadre(lignes, COLONNES_PONT)


def _n(valeur: float) -> str:
    """Nombre lisible dans une formule (sans zéros inutiles)."""
    return f"{valeur:.6g}"


def _cadre(lignes: list[dict], colonnes: list[str]) -> pd.DataFrame:
    """DataFrame avec des colonnes stables, même s'il n'y a aucun élément."""
    return pd.DataFrame(lignes, columns=colonnes)
