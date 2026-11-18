# Moteur de déperditions 3CL-DPE
Recalcule les déperditions statiques de l'enveloppe à partir d'un XML DPE ADEME et les compare aux valeurs de `<sortie><deperdition>`.
```
H_enveloppe = Σ H_murs + Σ H_planchers_bas + Σ H_planchers_hauts
            + Σ H_baies + Σ H_portes + Σ H_ponts_thermiques
```
| Poste | Formule | Source du U |
| --- | --- | --- |
| Mur | `surface_paroi_opaque × umur × b` | `umur` (jamais la surface totale, qui contient les baies) |
| Plancher bas | `surface_paroi_opaque × U × b` | `upb_final`, sinon `upb` |
| Plancher haut | `surface_paroi_opaque × uph × b` | `uph` |
| Baie | `surface_totale_baie × U × b` | `ujn` s'il existe, sinon `uw` |
| Porte | `surface_porte × uporte × b` | `uporte` |
| Pont thermique | `k × l × pourcentage × b` | `k` (W/m·K), pas un U surfacique |
`b` vaut 1 seulement si la balise est absente. Un `b` publié à 0 est conservé.
## Ce que contient `deperdition_enveloppe`
Sur le XML d'exemple, la balise officielle vaut la transmission **plus** le renouvellement d'air (`hvent + hperm`). Le moteur ne recalcule pas l'air. La comparaison le réaffiche à part, puis reconstitue la balise globale par :
`H_calculé + deperdition_renouvellement_air`.
L'écart résiduel sur le plancher bas (environ 0,00025 W/K) vient de `upb_final` publié à 5 décimales (`0.34711`) alors que le total ADEME a été produit avec le coefficient non arrondi.
## Lancer
Python 3.11 ou plus récent.
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\streamlit run app.py
```
`main.py` et `app.py` lisent `data/2671E0055558U.xml` si aucun fichier n'est fourni. L'interface Streamlit accepte aussi un autre XML DPE.
## Modules
- `parser.py` — modèles Pydantic et lecture XML tolérante aux balises optionnelles
- `calculator.py` — un DataFrame par poste, avec la formule appliquée
- `report.py` — synthèse (W/K et %) et tableau calculé / officiel / écart
- `tests/test_engine.py` — le total d'enveloppe doit retrouver la référence XML
- `app.py` — écran Streamlit (synthèse, comparaison, traçabilité)
