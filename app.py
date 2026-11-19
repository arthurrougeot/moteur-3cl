"""Interface Streamlit du moteur de déperditions 3CL."""
from __future__ import annotations

import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from calculator import calculer_enveloppe
from parser import DpeStructureError, parse_dpe
from report import SEUIL_ARRONDI_W_K

ECHANTILLON = Path(__file__).resolve().parent / "data" / "2671E0055558U.xml"


def _afficher(cadre: pd.DataFrame, formats: dict[str, str]) -> pd.DataFrame:
    vue = cadre.copy()
    for colonne, motif in formats.items():
        if colonne in vue.columns:
            vue[colonne] = vue[colonne].map(
                lambda valeur, motif=motif: ""
                if pd.isna(valeur)
                else motif.format(valeur)
            )
    return vue


st.set_page_config(page_title="Déperditions 3CL-DPE", layout="wide")
st.title("Déperditions d'enveloppe — méthode 3CL-DPE")
st.caption(
    "H = Σ (S × U × b) pour les parois, H = k × l × pourcentage × b pour les ponts, "
    "et DR = Hvent + Hperm pour le renouvellement d'air."
)

# --- Choix du fichier XML (glisser-déposer) ---
fichier = st.file_uploader("XML DPE ADEME", type=["xml"])
if fichier is not None:
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as temporaire:
        temporaire.write(fichier.getvalue())
        chemin = Path(temporaire.name)
    source = fichier.name
else:
    chemin = ECHANTILLON
    source = ECHANTILLON.name

if not chemin.exists():
    st.error(f"Fichier introuvable : {chemin}")
    st.stop()

# --- Lecture du XML puis calcul ---
try:
    dpe = parse_dpe(chemin)
    resultat = calculer_enveloppe(dpe)
except DpeStructureError as exc:
    st.error(f"Fichier XML incompatible : {exc}")
    st.stop()
except ValueError as exc:
    st.error(f"Données manquantes ou invalides dans le XML : {exc}")
    st.stop()

vent = resultat.ventilation

# --- Chiffres clés en haut de page ---
col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("DPE", dpe.numero_dpe or source)
col_b.metric(
    "Surface habitable",
    "—" if dpe.surface_habitable_m2 is None else f"{dpe.surface_habitable_m2:.1f} m²",
)
col_c.metric("H transmission (parois + ponts)", f"{resultat.h_transmission:.2f} W/K")
col_d.metric(
    "GV enveloppe (avec air)",
    f"{resultat.h_enveloppe:.2f} W/K",
    delta=(
        None
        if resultat.h_renouvellement_air is None
        else f"dont air : {resultat.h_renouvellement_air:.2f} W/K"
    ),
    delta_color="off",
)

# --- Statut visible du calcul de ventilation ---
if vent.calcule:
    st.success(
        f"**Ventilation recalculée (méthode 3CL-DPE)** : "
        f"DR = {vent.dr_w_k:.2f} W/K "
        f"(Hvent = {vent.hvent_w_k:.2f} W/K, Hperm = {vent.hperm_w_k:.2f} W/K)."
    )
elif vent.source == "reference_xml":
    causes = "\n".join(f"- {raison}" for raison in vent.raisons_echec)
    st.warning(
        "**Calcul des déperditions par ventilation non réalisé** — "
        f"repli sur la valeur de référence du XML "
        f"(`deperdition_renouvellement_air` = {vent.dr_w_k:.2f} W/K).\n\n"
        f"**Cause(s) identifiée(s) :**\n{causes}"
    )
else:
    causes = "\n".join(f"- {raison}" for raison in vent.raisons_echec)
    st.error(
        "**Déperditions par ventilation indisponibles** (calcul 3CL impossible et "
        "valeur de référence absente du XML).\n\n"
        f"**Cause(s) identifiée(s) :**\n{causes}"
    )

# --- Bandeau de validation (vert / rouge) par rapport à la référence ADEME ---
categorie_validation = (
    "Déperdition enveloppe XML"
    if vent.calcule
    else "Enveloppe transmission (parois + ponts)"
)
ligne_ref = resultat.comparaison.loc[
    resultat.comparaison["categorie"] == categorie_validation
].iloc[0]

ecart = ligne_ref["ecart_w_k"]
ecart_pct = ligne_ref["ecart_relatif_pct"]

if pd.isna(ecart):
    st.warning(
        f"Référence ADEME absente ou incomplète pour « {categorie_validation} » : "
        "impossible de vérifier automatiquement l'écart."
    )
elif abs(ecart) <= SEUIL_ARRONDI_W_K:
    st.success(
        f"Calcul conforme à la référence ADEME sur « {categorie_validation} » "
        f"(écart : {ecart:+.4f} W/K, tolérance admise : ±{SEUIL_ARRONDI_W_K} W/K)."
    )
else:
    detail_pct = "" if pd.isna(ecart_pct) else f", soit {ecart_pct:+.2f} %"
    st.error(
        f"Écart détecté par rapport à la référence ADEME sur « {categorie_validation} » : "
        f"{ecart:+.4f} W/K{detail_pct} (tolérance admise : ±{SEUIL_ARRONDI_W_K} W/K). "
        "Consultez l'onglet « Comparaison ADEME » pour identifier le poste en cause."
    )

onglet_synthese, onglet_comparaison, onglet_detail = st.tabs(
    ["Synthèse", "Comparaison ADEME", "Traçabilité"]
)

with onglet_synthese:
    # --- Graphique de la répartition (une barre par catégorie) ---
    repartition = resultat.synthese[
        ~resultat.synthese["categorie"].str.startswith("Enveloppe")
    ].assign(etiquette=lambda d: d["part_pct"].map("{:.1f} %".format))
    barres = (
        alt.Chart(repartition)
        .mark_bar()
        .encode(
            x=alt.X("deperdition_w_k:Q", title="Déperdition (W/K)"),
            y=alt.Y("categorie:N", sort="-x", title=None),
            tooltip=[
                alt.Tooltip("categorie:N", title="Poste"),
                alt.Tooltip("deperdition_w_k:Q", title="W/K", format=".2f"),
                alt.Tooltip("part_pct:Q", title="Part (%)", format=".1f"),
                alt.Tooltip("source:N", title="Source"),
            ],
        )
    )
    pourcentages = barres.mark_text(align="left", dx=4).encode(text="etiquette:N")
    st.subheader("Répartition des déperditions")
    st.altair_chart(barres + pourcentages, use_container_width=True)

    # --- Tableau de synthèse ---
    st.dataframe(
        _afficher(resultat.synthese, {"deperdition_w_k": "{:.4f}", "part_pct": "{:.2f}"}),
        use_container_width=True,
        hide_index=True,
    )

with onglet_comparaison:
    st.dataframe(
        _afficher(
            resultat.comparaison,
            {
                "calcule_w_k": "{:.4f}",
                "officiel_w_k": "{:.4f}",
                "ecart_w_k": "{:.6f}",
                "ecart_relatif_pct": "{:.4f}",
            },
        ),
        use_container_width=True,
        hide_index=True,
    )
    if vent.calcule:
        st.info(
            "Le renouvellement d'air (DR = Hvent + Hperm) est recalculé selon la méthode "
            "3CL-DPE et inclus dans la ligne « Déperdition enveloppe XML »."
        )
    else:
        st.info(
            "Le renouvellement d'air n'ayant pas pu être recalculé, la ligne "
            "« Déperdition enveloppe XML » additionne la transmission calculée "
            "et la valeur de référence XML du renouvellement d'air."
        )

with onglet_detail:
    for cle, cadre in resultat.details.items():
        st.subheader(cle.replace("_", " ").capitalize())
        st.dataframe(cadre, use_container_width=True, hide_index=True)