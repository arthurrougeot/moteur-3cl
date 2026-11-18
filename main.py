"""Rapport console : détail, synthèse et comparaison au XML ADEME."""
from __future__ import annotations
import argparse
from pathlib import Path
from calculator import calculer_enveloppe
from parser import parse_dpe
ECHANTILLON = Path(__file__).resolve().parent / "data" / "2671E0055558U.xml"
def main() -> None:
    arguments = argparse.ArgumentParser(description="Déperditions d'enveloppe 3CL-DPE")
    arguments.add_argument(
        "xml",
        nargs="?",
        default=str(ECHANTILLON),
        help="chemin du XML DPE ADEME",
    )
    chemin = Path(arguments.parse_args().xml)
    dpe = parse_dpe(chemin)
    resultat = calculer_enveloppe(dpe)
    print(f"DPE {dpe.numero_dpe or chemin.name}")
    if dpe.surface_habitable_m2 is not None:
        print(f"Surface habitable : {dpe.surface_habitable_m2:g} m²")
    print(f"H_enveloppe (parois + ponts) = {resultat.h_enveloppe:.6f} W/K")
    print()
    for cle, cadre in resultat.details.items():
        print(f"--- {cle} ---")
        print(cadre.to_string(index=False))
        print()
    print("--- synthèse ---")
    print(resultat.synthese.to_string(index=False))
    print()
    print("--- comparaison avec <sortie><deperdition> ---")
    print(resultat.comparaison.to_string(index=False))
if __name__ == "__main__":
    main()
