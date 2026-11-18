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
    "H = Σ (S × U × b) pour les parois, et H = k × l × pourcentage × b pour les ponts. "
    "Le renouvellement d'air du XML n'est pas recalculé."
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

# --- Chiffres clés en haut de page ---
colonne_a, colonne_b, colonne_c = st.columns(3)
colonne_a.metric("DPE", dpe.numero_dpe or source)
colonne_b.metric(
    "Surface habitable",
    "—" if dpe.surface_habitable_m2 is None else f"{dpe.surface_habitable_m2:.1f} m²",
)
colonne_c.metric("H enveloppe", f"{resultat.h_enveloppe:.2f} W/K")

# --- Bandeau de validation (vert / rouge) par rapport à la référence ADEME ---
ligne_ref = resultat.comparaison.loc[
    resultat.comparaison["categorie"] == "Enveloppe transmission (parois + ponts)"
].iloc[0]

ecart = ligne_ref["ecart_w_k"]
ecart_pct = ligne_ref["ecart_relatif_pct"]

if pd.isna(ecart):
    st.warning(
        "Référence ADEME absente ou incomplète dans le XML : "
        "impossible de vérifier automatiquement l'écart."
    )
elif abs(ecart) <= SEUIL_ARRONDI_W_K:
    st.success(
        f"Calcul conforme à la référence ADEME "
        f"(écart : {ecart:+.4f} W/K, tolérance admise : ±{SEUIL_ARRONDI_W_K} W/K)."
    )
else:
    detail_pct = "" if pd.isna(ecart_pct) else f", soit {ecart_pct:+.2f} %"
    st.error(
        f"Écart détecté par rapport à la référence ADEME : "
        f"{ecart:+.4f} W/K{detail_pct} (tolérance admise : ±{SEUIL_ARRONDI_W_K} W/K). "
        "Consultez l'onglet « Comparaison ADEME » pour identifier le poste en cause."
    )

onglet_synthese, onglet_comparaison, onglet_detail = st.tabs(
    ["Synthèse", "Comparaison ADEME", "Traçabilité"]
)

with onglet_synthese:
    # --- Graphique de la répartition (une barre par catégorie) ---
    repartition = resultat.synthese[
        resultat.synthese["categorie"] != "Enveloppe (parois + ponts)"
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
            ],
        )
    )
    pourcentages = barres.mark_text(align="left", dx=4).encode(text="etiquette:N")
    st.subheader("Répartition des déperditions")
    st.altair_chart(barres + pourcentages)

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
    st.info(
        "deperdition_enveloppe du XML vaut la transmission plus le renouvellement d'air. "
        "La ligne « Déperdition enveloppe XML » additionne le H calculé et l'air officiel."
    )

with onglet_detail:
    for cle, cadre in resultat.details.items():
        st.subheader(cle.replace("_", " "))
        st.dataframe(cadre, use_container_width=True, hide_index=True)