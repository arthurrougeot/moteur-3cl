"""Déperditions de l'enveloppe, méthode 3CL-DPE.

GV = Σ H_murs + Σ H_planchers_bas + Σ H_planchers_hauts
   + Σ H_baies + Σ H_portes + Σ H_ponts_thermiques + DR

Avec DR = Hvent + Hperm (chapitre 4 de l'Annexe 1 3CL-DPE 2021).
Les débits (Qvarep_conv, Qvasouf_conv, Smea_conv) sont lus en priorité via
``tv_debits_ventilation_id`` (index 1..38 du tableau officiel), puis via
``description`` si l'ID est absent. En cas d'échec, le moteur se replie sur
``deperdition_renouvellement_air`` du XML et consigne la cause exacte.
"""
from __future__ import annotations

import re
import unicodedata
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
    Ventilation,
)
from report import comparer, synthetiser

# Chaleur volumique de l'air : 0,34 Wh/(m³.K)
CHALEUR_VOLUMIQUE_AIR = 0.34

# Tableau officiel 3CL-DPE (Annexe 1, chap. 4, p. 40) dans l'ordre exact des 38 lignes :
# tv_debits_ventilation_id (1..38) -> (Type de ventilation, (Qvarep_conv, Qvasouf_conv, Smea_conv))
TABLE_DEBITS_PAR_ID: dict[int, tuple[str, tuple[float, float, float]]] = {
    1: ("Ventilation par ouverture des fenêtres", (1.20, 1.20, 0.0)),
    2: ("Ventilation par entrées d'air hautes et basses", (2.23, 0.0, 4.0)),
    3: ("VMC SF Auto réglable < 1982", (1.97, 0.0, 2.0)),
    4: ("VMC SF Auto réglable de 1982 à 2000", (1.65, 0.0, 2.0)),
    5: ("VMC SF Auto réglable de 2001 à 2012", (1.50, 0.0, 2.0)),
    6: ("VMC SF Auto réglable après 2012", (1.32, 0.0, 2.0)),
    7: ("VMC SF Hygro A < 2001", (1.50, 0.0, 2.0)),
    8: ("VMC SF Hygro A de 2001 à 2012", (1.44, 0.0, 2.0)),
    9: ("VMC SF Hygro A après 2012", (1.16, 0.0, 2.0)),
    10: ("VMC SF Gaz < 2001", (1.59, 0.0, 2.0)),
    11: ("VMC SF Gaz de 2001 à 2012", (1.53, 0.0, 2.0)),
    12: ("VMC SF Gaz après 2012", (1.22, 0.0, 2.0)),
    13: ("VMC SF Hygro B < 2001", (1.36, 0.0, 1.5)),
    14: ("VMC SF Hygro B de 2001 à 2012", (1.24, 0.0, 1.5)),
    15: ("VMC SF Hygro B après 2012", (1.09, 0.0, 1.5)),
    16: ("VMC Basse pression Auto-réglable", (1.97, 0.0, 2.0)),
    17: ("VMC Basse pression Hygro A", (1.30, 0.0, 2.0)),
    18: ("VMC Basse pression Hygro B", (1.24, 0.0, 1.5)),
    19: ("VMC DF individuelle avec échangeur ≤ 2012", (0.60, 0.60, 0.0)),
    20: ("VMC DF individuelle avec échangeur après 2012", (0.26, 0.26, 0.0)),
    21: ("VMC DF collective avec échangeur ≤ 2012", (0.75, 0.75, 0.0)),
    22: ("VMC DF collective avec échangeur après 2012", (0.46, 0.46, 0.0)),
    23: ("VMC DF sans échangeur ≤ 2012", (1.65, 1.65, 0.0)),
    24: ("VMC DF sans échangeur après 2012", (1.32, 1.32, 0.0)),
    25: ("Ventilation naturelle par conduit", (2.23, 0.0, 4.0)),
    26: ("Ventilation hybride < 2001", (1.52, 0.0, 3.0)),
    27: ("Ventilation hybride de 2001 à 2012", (1.33, 0.0, 3.0)),
    28: ("Ventilation hybride après 2012", (1.17, 0.0, 3.0)),
    29: ("Ventilation hybride avec entrées d'air hygro < 2001", (1.52, 0.0, 2.0)),
    30: ("Ventilation hybride avec entrées d'air hygro de 2001 à 2012", (1.33, 0.0, 2.0)),
    31: ("Ventilation hybride avec entrées d'air hygro après 2012", (1.17, 0.0, 2.0)),
    32: ("Ventilation mécanique sur conduit existant ≤ 2012", (2.24, 0.0, 4.0)),
    33: ("Ventilation mécanique sur conduit existant après 2012", (1.97, 0.0, 4.0)),
    34: ("Ventilation naturelle par conduit avec entrées d'air hygro", (2.23, 0.0, 3.0)),
    35: ("Puits climatique sans échangeur ≤ 2012", (0.99, 0.99, 0.0)),
    36: ("Puits climatique sans échangeur après 2012", (0.79, 0.79, 0.0)),
    37: ("Puits climatique avec échangeur ≤ 2012", (0.36, 0.36, 0.0)),
    38: ("Puits climatique avec échangeur après 2012", (0.16, 0.16, 0.0)),
}

TABLE_DEBITS_VENTILATION: dict[str, tuple[float, float, float]] = {
    libelle: debits for libelle, debits in TABLE_DEBITS_PAR_ID.values()
}

# Alias pour la ligne tronquée dans le PDF officiel ("... de 2001 à")
_ALIAS_TABLE_VENTILATION: dict[str, str] = {
    "Ventilation hybride avec entrées d'air hygro de 2001 à": (
        "Ventilation hybride avec entrées d'air hygro de 2001 à 2012"
    ),
}

# Tableau officiel 3CL-DPE (Annexe 1, chap. 4, p. 39) :
# plusieurs_facade_exposee (0 ou 1) -> (e, f)
TABLE_PROTECTION_VENT: dict[int, tuple[float, float]] = {
    1: (0.07, 15.0),  # Plusieurs façades exposées
    0: (0.02, 20.0),  # Une seule façade exposée
}

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
COLONNES_VENTILATION = [
    "description_xml",
    "tv_debits_ventilation_id",
    "entree_table_3cl",
    "source_identification",
    "statut",
    "surface_ventile_m2",
    "hsp_m",
    "sdep_m2",
    "qvarep_conv",
    "qvasouf_conv",
    "smea_conv",
    "plusieurs_facades",
    "e",
    "f",
    "q4pa_conv",
    "q4pa_env",
    "q4pa",
    "n50_h_1",
    "qvinf_m3_h",
    "hvent_w_k",
    "hperm_w_k",
    "deperdition_w_k",
    "formule",
    "reference",
]


def _normaliser_texte(texte: str) -> str:
    """Normalise une chaîne pour fiabiliser la correspondance XML / tableau 3CL."""
    sans_accents = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texte)
        if not unicodedata.combining(caractere)
    )
    propre = sans_accents.lower()
    propre = propre.replace("’", "'").replace("`", "'")
    propre = propre.replace("≤", " <= ").replace("≥", " >= ")
    propre = re.sub(r"<=", " <= ", propre)
    propre = re.sub(r"(?<![<>])<(?!=)", " < ", propre)
    propre = propre.replace("auto-reglable", "auto reglable")
    propre = propre.replace("autoreglable", "auto reglable")
    propre = propre.replace("avant 1982", "< 1982")
    propre = propre.replace("avant 2001", "< 2001")
    propre = propre.replace("avant 2013", "<= 2012")
    propre = propre.replace("jusqu'a 2012", "<= 2012")
    propre = propre.replace("-", " ")
    propre = re.sub(r"\s+", " ", propre).strip()
    return propre


_INDEX_VENTILATION: dict[str, str] = {
    _normaliser_texte(libelle): libelle for libelle in TABLE_DEBITS_VENTILATION
}
for _alias, _cible in _ALIAS_TABLE_VENTILATION.items():
    _INDEX_VENTILATION[_normaliser_texte(_alias)] = _cible

_CLES_TRIEES: list[tuple[str, str]] = sorted(
    _INDEX_VENTILATION.items(),
    key=lambda item: len(item[0]),
    reverse=True,
)


def identifier_debits_ventilation(
    vent: Ventilation,
) -> tuple[str, tuple[float, float, float], str] | None:
    """Résout ``(libellé_table, (Qvarep, Qvasouf, Smea), source_identification)``.

    1. Priorité à ``tv_debits_ventilation_id`` (index 1..38 du tableau officiel).
    2. Repli sur la chaîne ``description`` normalisée.
    """
    if vent.tv_debits_ventilation_id in TABLE_DEBITS_PAR_ID:
        libelle, debits = TABLE_DEBITS_PAR_ID[vent.tv_debits_ventilation_id]
        return libelle, debits, f"tv_debits_ventilation_id={vent.tv_debits_ventilation_id}"

    if vent.description and vent.description.strip():
        desc_norm = _normaliser_texte(vent.description)
        if desc_norm in _INDEX_VENTILATION:
            libelle = _INDEX_VENTILATION[desc_norm]
            return libelle, TABLE_DEBITS_VENTILATION[libelle], "description (exacte)"

        for cle_norm, libelle in _CLES_TRIEES:
            motif = rf"(?:^|[^a-z0-9]){re.escape(cle_norm)}(?:$|[^a-z0-9])"
            if re.search(motif, desc_norm):
                return libelle, TABLE_DEBITS_VENTILATION[libelle], "description (partielle)"

    return None


@dataclass
class ResultatVentilation:
    calcule: bool
    source: str  # "calcul_3cl" | "reference_xml" | "indisponible"
    hvent_w_k: float | None
    hperm_w_k: float | None
    dr_w_k: float | None
    raisons_echec: list[str]
    details: pd.DataFrame


@dataclass
class ResultatCalcul:
    details: dict[str, pd.DataFrame]
    synthese: pd.DataFrame
    comparaison: pd.DataFrame
    h_par_categorie: dict[str, float]
    h_transmission: float
    h_renouvellement_air: float | None
    h_enveloppe: float
    ventilation: ResultatVentilation


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
    h_transmission = sum(h_par_categorie.values())

    ventilation = calculer_ventilation(dpe)
    details["ventilation"] = ventilation.details

    h_air = ventilation.dr_w_k
    h_enveloppe = h_transmission + (h_air if h_air is not None else 0.0)

    return ResultatCalcul(
        details=details,
        synthese=synthetiser(
            h_par_categorie,
            dr_w_k=h_air,
            source_air=ventilation.source,
        ),
        comparaison=comparer(
            h_par_categorie,
            dpe.deperdition,
            dr_w_k=h_air,
            air_calcule=ventilation.calcule,
        ),
        h_par_categorie=h_par_categorie,
        h_transmission=h_transmission,
        h_renouvellement_air=h_air,
        h_enveloppe=h_enveloppe,
        ventilation=ventilation,
    )


def calculer_sdep(dpe: Dpe) -> float:
    """Surface des parois déperditives (b > 0) hors planchers bas, en m²."""
    s_murs = sum(m.surface_paroi_opaque for m in dpe.murs if m.b > 0)
    s_ph = sum(p.surface_paroi_opaque for p in dpe.planchers_hauts if p.b > 0)
    s_baies = sum(b.surface_totale_baie for b in dpe.baies if b.b > 0)
    s_portes = sum(p.surface_porte for p in dpe.portes if p.b > 0)
    return s_murs + s_ph + s_baies + s_portes


def calculer_ventilation(dpe: Dpe) -> ResultatVentilation:
    """Calcule DR = Hvent + Hperm (W/K) ou se replie sur la référence XML."""
    raisons: list[str] = []
    lignes: list[dict] = []
    sdep_totale = calculer_sdep(dpe)
    hsp = dpe.hsp_m

    if not dpe.ventilations:
        raisons.append(
            "Aucune balise <ventilation> trouvée dans <logement><ventilation_collection>."
        )

    if hsp is None or hsp <= 0:
        raisons.append(
            "Balise <hsp> (hauteur moyenne sous plafond) absente ou invalide "
            "dans <caracteristique_generale>."
        )

    surfaces_valides = [
        v.surface_ventile
        for v in dpe.ventilations
        if v.surface_ventile is not None and v.surface_ventile > 0
    ]
    sh_ventilee_totale = sum(surfaces_valides) if surfaces_valides else 0.0

    hvent_total = 0.0
    hperm_total = 0.0
    toutes_calculables = bool(dpe.ventilations) and hsp is not None and hsp > 0

    for indice, vent in enumerate(dpe.ventilations, start=1):
        etiquette = f"Ventilation #{indice}"
        manquants_element: list[str] = []

        identification = identifier_debits_ventilation(vent)
        if identification is None:
            detail_id = (
                f"tv_debits_ventilation_id={vent.tv_debits_ventilation_id}"
                if vent.tv_debits_ventilation_id is not None
                else "tv_debits_ventilation_id absent"
            )
            detail_desc = (
                f"description « {vent.description} »"
                if vent.description
                else "description vide/absente"
            )
            manquants_element.append(
                f"{etiquette} : type de ventilation non résolu ({detail_id}, {detail_desc})."
            )

        if vent.surface_ventile is None or vent.surface_ventile <= 0:
            manquants_element.append(
                f"{etiquette} : balise <donnee_entree><surface_ventile> absente ou nulle."
            )

        if vent.plusieurs_facade_exposee not in TABLE_PROTECTION_VENT:
            manquants_element.append(
                f"{etiquette} : balise <donnee_entree><plusieurs_facade_exposee> "
                "absente ou différente de 0/1."
            )

        if vent.q4pa_conv is None:
            manquants_element.append(
                f"{etiquette} : balise <donnee_intermediaire><q4pa_conv> absente."
            )

        if manquants_element or hsp is None or hsp <= 0:
            toutes_calculables = False
            raisons.extend(manquants_element)
            lignes.append(
                {
                    "description_xml": vent.description or "—",
                    "tv_debits_ventilation_id": vent.tv_debits_ventilation_id,
                    "entree_table_3cl": identification[0] if identification else "Non trouvée",
                    "source_identification": identification[2] if identification else "Aucune",
                    "statut": "Non calculé : " + " | ".join(manquants_element or ["hsp absent"]),
                    "surface_ventile_m2": vent.surface_ventile,
                    "hsp_m": hsp,
                    "sdep_m2": None,
                    "qvarep_conv": identification[1][0] if identification else None,
                    "qvasouf_conv": identification[1][1] if identification else None,
                    "smea_conv": identification[1][2] if identification else None,
                    "plusieurs_facades": vent.plusieurs_facade_exposee,
                    "e": (
                        TABLE_PROTECTION_VENT[vent.plusieurs_facade_exposee][0]
                        if vent.plusieurs_facade_exposee in TABLE_PROTECTION_VENT
                        else None
                    ),
                    "f": (
                        TABLE_PROTECTION_VENT[vent.plusieurs_facade_exposee][1]
                        if vent.plusieurs_facade_exposee in TABLE_PROTECTION_VENT
                        else None
                    ),
                    "q4pa_conv": vent.q4pa_conv,
                    "q4pa_env": None,
                    "q4pa": None,
                    "n50_h_1": None,
                    "qvinf_m3_h": None,
                    "hvent_w_k": None,
                    "hperm_w_k": None,
                    "deperdition_w_k": None,
                    "formule": "Repli sur la référence XML",
                    "reference": vent.reference,
                }
            )
            continue

        assert identification is not None
        assert vent.surface_ventile is not None
        assert vent.plusieurs_facade_exposee is not None
        assert vent.q4pa_conv is not None

        libelle_table, (qvarep, qvasouf, smea), source_id = identification
        sh = vent.surface_ventile
        e, f = TABLE_PROTECTION_VENT[vent.plusieurs_facade_exposee]

        ratio_surface = sh / sh_ventilee_totale if sh_ventilee_totale > 0 else 1.0
        sdep = sdep_totale * ratio_surface

        # 1. Déperdition par ventilation (W/K)
        hvent = CHALEUR_VOLUMIQUE_AIR * qvarep * sh

        # 2. Déperdition par infiltrations / perméabilité (W/K)
        q4pa_env = vent.q4pa_conv * sdep
        q4pa = q4pa_env + 0.45 * smea * sh
        n50 = q4pa / (((4.0 / 50.0) ** (2.0 / 3.0)) * hsp * sh)

        if n50 <= 0:
            qvinf = 0.0
        else:
            terme_vent = (f / e) * (((qvasouf - qvarep) / (hsp * n50)) ** 2)
            qvinf = (hsp * sh * n50 * e) / (1.0 + terme_vent)

        hperm = CHALEUR_VOLUMIQUE_AIR * qvinf
        dr = hvent + hperm

        hvent_total += hvent
        hperm_total += hperm

        lignes.append(
            {
                "description_xml": vent.description or "—",
                "tv_debits_ventilation_id": vent.tv_debits_ventilation_id,
                "entree_table_3cl": libelle_table,
                "source_identification": source_id,
                "statut": "Calculé (3CL-DPE)",
                "surface_ventile_m2": sh,
                "hsp_m": hsp,
                "sdep_m2": sdep,
                "qvarep_conv": qvarep,
                "qvasouf_conv": qvasouf,
                "smea_conv": smea,
                "plusieurs_facades": vent.plusieurs_facade_exposee,
                "e": e,
                "f": f,
                "q4pa_conv": vent.q4pa_conv,
                "q4pa_env": q4pa_env,
                "q4pa": q4pa,
                "n50_h_1": n50,
                "qvinf_m3_h": qvinf,
                "hvent_w_k": hvent,
                "hperm_w_k": hperm,
                "deperdition_w_k": dr,
                "formule": (
                    f"Hvent = 0.34 * {_n(qvarep)} * {_n(sh)} = {_n(hvent)} W/K ; "
                    f"Hperm = 0.34 * {_n(qvinf)} = {_n(hperm)} W/K ; "
                    f"DR = {_n(dr)} W/K"
                ),
                "reference": vent.reference,
            }
        )

    cadre_ventilation = _cadre(lignes, COLONNES_VENTILATION)

    if toutes_calculables:
        return ResultatVentilation(
            calcule=True,
            source="calcul_3cl",
            hvent_w_k=hvent_total,
            hperm_w_k=hperm_total,
            dr_w_k=hvent_total + hperm_total,
            raisons_echec=[],
            details=cadre_ventilation,
        )

    ref_air = dpe.deperdition.valeur("deperdition_renouvellement_air")
    ref_hvent = dpe.deperdition.valeur("hvent")
    ref_hperm = dpe.deperdition.valeur("hperm")

    if ref_air is not None:
        return ResultatVentilation(
            calcule=False,
            source="reference_xml",
            hvent_w_k=ref_hvent,
            hperm_w_k=ref_hperm,
            dr_w_k=ref_air,
            raisons_echec=raisons,
            details=cadre_ventilation,
        )

    raisons.append(
        "Balise de repli <sortie><deperdition><deperdition_renouvellement_air> "
        "également absente du XML."
    )
    return ResultatVentilation(
        calcule=False,
        source="indisponible",
        hvent_w_k=None,
        hperm_w_k=None,
        dr_w_k=None,
        raisons_echec=raisons,
        details=cadre_ventilation,
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