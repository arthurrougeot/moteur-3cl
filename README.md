# Moteur de déperditions 3CL-DPE

Application Python / Streamlit permettant de lire un fichier XML issu de l'Observatoire DPE-Audit de l'ADEME, de calculer les déperditions thermiques de l'enveloppe selon la méthode **3CL-DPE (2021)** et de comparer les résultats aux valeurs de référence publiées dans `<sortie><deperdition>`.

Les calculs sont basés sur le document officiel `consolide_annexe_1_arrete_du_31_03_2021_relatif_aux_methodes_et_procedures_applicables.pdf`.

## Référentiel normatif utilisé

- **Méthode de calcul 3CL-DPE 2021 (Annexe 1 de l'arrêté du 31 mars 2021)** : document officiel `consolide_annexe_1_arrete_du_31_03_2021_relatif_aux_methodes_et_procedures_applicables.pdf`, version consolidée du ministère (mise à jour octobre 2021).
- **Guide DPE Logements — Guide à l'usage des diagnostiqueurs** (Cerema / DHUP, version 3 — juillet 2024) et textes modificatifs (dont l'arrêté du 25 mars 2024).

> Note de version : le PDF consolidé `consolide_annexe_1_arrete_du_31_03_2021_relatif_aux_methodes_et_procedures_applicables.pdf` correspond à la mise à jour d'octobre 2021 et n'intègre pas directement les modifications réglementaires de 2024 dans son texte consolidé.

## Installation et lancement

Prérequis : Python 3.11 ou plus récent.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\streamlit run app.py
```
Pour lancer la page web dans un nouveau terminal, exécute :

```powershell
.\.venv\Scripts\streamlit run app.py


`main.py` et `app.py` lisent le fichier d'exemple par défaut si aucun XML n'est déposé. L'interface Streamlit permet de glisser-déposer un autre fichier XML DPE ADEME.

```markdown
## Jeux d'essai XML et rapports

Le moteur est testé sur plusieurs fichiers XML de l'Observatoire DPE-Audit ADEME représentant des configurations variées (par exemple : maison ancienne, maison récente, appartement ou studio récent), en vérifiant la conformité des totaux aux balises `<sortie><deperdition>` dans la limite du seuil d'arrondi (`0,01 W/K`) et le comportement des garde-fous (versions XSD, exclusions, replis).

## Périmètre et formules

### Dans le périmètre

```text
GV = Σ H_murs + Σ H_planchers_bas + Σ H_planchers_hauts
   + Σ H_baies + Σ H_portes + Σ H_ponts_thermiques + DR
```

| Poste | Formule | Source / Règle |
| --- | --- | --- |
| Mur | `surface_paroi_opaque × umur × b` | `umur` (jamais la surface totale, qui inclut les baies) |
| Plancher bas | `surface_paroi_opaque × U × b` | `upb_final` s'il est publié, sinon `upb` |
| Plancher haut | `surface_paroi_opaque × uph × b` | `uph` |
| Baie vitrée | `surface_totale_baie × U × b` | `ujn` en priorité s'il existe (présence de volets/fermetures pouvant être fermés sur certaines périodes), sinon `uw` |
| Porte | `surface_porte × uporte × b` | `uporte` |
| Pont thermique | `k × l × pourcentage × b` | `k` (en W/m.K), pas un U surfacique |
| Renouvellement d'air | `DR = Hvent + Hperm` | Chapitre 4 de l'Annexe 1 deu PDf consolid... : `Hvent = 0,34 × Qvarep_conv × Sh` et `Hperm = 0,34 × Qvinf` (avec `Q4Pa_env = q4pa_conv × Sdep`, `Q4Pa = Q4Pa_env + 0,45 × Smea_conv × Sh`, `n50 = Q4Pa / ((4/50)^(2/3) × hsp × Sh)` et coefficients `e`, `f` selon `plusieurs_facade_exposee`) |

`b` vaut `1` seulement si la balise est absente. Un `b` publié à `0` est conservé.

### Hors périmètre

- Besoins et consommations des 5 usages (chauffage, ECS, refroidissement, éclairage, auxiliaires).
- Émissions de gaz à effet de serre (GES), coûts énergétiques, recommandations de travaux et étiquettes DPE (A à G).
- Recalcul depuis zéro des coefficients `U`, `b` ou `k` à partir des matériaux bruts ou des abaques d'enveloppe / ponts thermiques (ces valeurs sont lues dans `<donnee_intermediaire>`).

## Hypothèses, garde-fous et points de vigilance

- **Priorité de `ujn` sur `uw` :** on utilise `ujn` en priorité sur `uw` quand il est présent, car cela signifie qu'il y a des volets (ou fermetures) et que l'on peut les fermer sur certaines périodes ; sinon on utilise `uw`.
- **Seuil d'arrondi (`SEUIL_ARRONDI_W_K = 0,01 W/K`) :** les coefficients `U` publiés dans le XML ADEME sont arrondis (souvent à 5 décimales), ce qui crée un résidu d'arrondi de l'ordre de `10^-4` à `10^-3 W/K`. Un seuil à `0,01 W/K` absorbe ces arrondis sans masquer une vraie erreur de formule ou une paroi oubliée.
- **Ventilation et repli :** les débits `(Qvarep_conv, Qvasouf_conv, Smea_conv)` sont cherchés en priorité via `tv_debits_ventilation_id` (lignes 1 à 38 du tableau de l'Annexe 1), puis par correspondance normalisée sur `<description>`. Les paramètres `e` et `f` dépendent de `plusieurs_facade_exposee` (`1` -> `e = 0,07`, `f = 15` ; `0` -> `e = 0,02`, `f = 20`). Si une donnée manque ou n'est pas reconnue, le moteur utilise en repli `deperdition_renouvellement_air` du XML et affiche la cause exacte dans l'interface.
- **Surface habitable :** lue en priorité dans `surface_habitable_logement`, avec repli sur `surface_habitable_immeuble` si nécessaire (cas de certains DPE immeuble).
- **Versions XSD et exclusions :** les **Audits énergétiques** et les **DPE neufs** (données issues de l'étude thermique RSET/RSEE, `<enveloppe>` souvent vide ou absente) sont rejetés avec un message explicite. Les versions antérieures aux versions stabilisées (`< 2.1`) affichent un avertissement ; les versions stabilisées (`>= 2.1`) affichent un message indiquant qu'il n'y a normalement pas de problème avec ce DPE.

## Structure du projet

- `app.py` : interface Streamlit (statut version/ventilation, synthèse, graphique, comparaison ADEME, traçabilité).
- `parser.py` : parsing XML (`ElementTree`) et modèles typés (`pydantic`).
- `calculator.py` : calcul des déperditions par poste (parois, ponts thermiques et renouvellement d'air).
- `report.py` : agrégation de synthèse et comparaison avec `<sortie><deperdition>`.
- `main.py` : exécution en ligne de commande.
- `tests/test_engine.py` : tests unitaires `pytest`.