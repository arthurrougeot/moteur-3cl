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

def generer_rapport_html(
    dpe: "Dpe",
    resultat: "ResultatCalcul",
    source_nom: str = "dpe.xml",
) -> str:
    """Génère un rapport HTML autonome à partir d'un Dpe et de son ResultatCalcul."""
    import html

    def _df_to_html(df: pd.DataFrame) -> str:
        if df.empty:
            return "<p><em>Aucun élément dans cette catégorie.</em></p>"
        copie = df.copy()
        for col in copie.select_dtypes(include=["float", "int"]).columns:
            copie[col] = copie[col].map(
                lambda v: "" if pd.isna(v) else f"{v:.4f}" if isinstance(v, float) else str(v)
            )
        copie = copie.fillna("")
        return copie.to_html(index=False, border=0, classes="table-3cl")

    vent = resultat.ventilation
    if vent.calcule:
        vent_bloc = (
            f"<div class='badge ok'>Ventilation recalculée (3CL-DPE) : "
            f"DR = {vent.dr_w_k:.4f} W/K (Hvent = {vent.hvent_w_k:.4f} W/K, "
            f"Hperm = {vent.hperm_w_k:.4f} W/K)</div>"
        )
    else:
        causes_html = "".join(
            f"<li>{html.escape(r)}</li>" for r in vent.raisons_echec
        )
        dr_txt = f"{vent.dr_w_k:.4f} W/K" if vent.dr_w_k is not None else "indisponible"
        vent_bloc = (
            f"<div class='badge warn'>Ventilation non recalculée — repli référence XML "
            f"({dr_txt})<ul>{causes_html}</ul></div>"
        )

    blocs_details = []
    for cle, cadre in resultat.details.items():
        titre = html.escape(cle.replace("_", " ").capitalize())
        blocs_details.append(f"<h3>{titre}</h3>\n{_df_to_html(cadre)}")

    sh_txt = (
        f"{dpe.surface_habitable_m2:.2f} m²"
        if dpe.surface_habitable_m2 is not None
        else "—"
    )
    num_dpe = html.escape(dpe.numero_dpe or source_nom)
    version_txt = html.escape(dpe.version_xsd or "non renseignée")

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Rapport 3CL-DPE — {num_dpe}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; line-height: 1.45; }}
  h1, h2, h3 {{ color: #111827; margin-top: 20px; }}
  .meta {{ display: flex; gap: 24px; flex-wrap: wrap; background: #f3f4f6; padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; }}
  .badge {{ padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; }}
  .badge.ok {{ background: #ecfdf5; border-left: 4px solid #10b981; }}
  .badge.warn {{ background: #fffbeb; border-left: 4px solid #f59e0b; }}
  table.table-3cl {{ border-collapse: collapse; width: 100%; margin-bottom: 16px; font-size: 13px; }}
  table.table-3cl th, table.table-3cl td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
  table.table-3cl th {{ background: #e5e7eb; }}
</style>
</head>
<body>
  <h1>Rapport de déperditions d'enveloppe — 3CL-DPE</h1>
  <div class="meta">
    <div><strong>DPE :</strong> {num_dpe}</div>
    <div><strong>Fichier :</strong> {html.escape(source_nom)}</div>
    <div><strong>Version XSD :</strong> {version_txt}</div>
    <div><strong>Surface habitable :</strong> {sh_txt}</div>
    <div><strong>H transmission :</strong> {resultat.h_transmission:.4f} W/K</div>
    <div><strong>GV enveloppe :</strong> {resultat.h_enveloppe:.4f} W/K</div>
  </div>
  {vent_bloc}
  <h2>Synthèse</h2>
  {_df_to_html(resultat.synthese)}
  <h2>Comparaison avec la référence XML</h2>
  {_df_to_html(resultat.comparaison)}
  <h2>Traçabilité détaillée par poste</h2>
  {"".join(blocs_details)}
</body>
</html>
"""