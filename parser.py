"""Lecture d'un XML de DPE (schéma ADEME 3CL) vers des modèles typés.
Les balises optionnelles (``ujn``, ``upb_final``, ``b``, pourcentage de pont
thermique) restent absentes plutôt que de faire échouer le parse. Les
coefficients vraiment nécessaires au calcul sont exigés au moment du calcul.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import IO, Iterable, Union

from pydantic import BaseModel, Field

SourceXml = Union[str, Path, IO[bytes]]


class DpeStructureError(ValueError):
    """Levée quand le XML est corrompu ou d'une structure incompatible."""


class Mur(BaseModel):
    description: str
    reference: str | None = None
    surface_paroi_opaque: float = Field(description="m², hors baies")
    umur: float = Field(description="W/m².K")
    b: float = Field(1.0, description="coefficient de réduction des déperditions")


class PlancherBas(BaseModel):
    description: str
    reference: str | None = None
    surface_paroi_opaque: float
    upb: float | None = None
    upb_final: float | None = None
    b: float = 1.0

    def coefficient_u(self) -> tuple[float, str]:
        """``upb_final`` s'il est publié, sinon ``upb``."""
        if self.upb_final is not None:
            return self.upb_final, "upb_final"
        if self.upb is not None:
            return self.upb, "upb"
        raise ValueError(
            f"{self.description}: ni upb_final ni upb dans donnee_intermediaire"
        )


class PlancherHaut(BaseModel):
    description: str
    reference: str | None = None
    surface_paroi_opaque: float
    uph: float
    b: float = 1.0


class BaieVitree(BaseModel):
    description: str
    reference: str | None = None
    surface_totale_baie: float
    uw: float | None = None
    ujn: float | None = None
    b: float = 1.0

    def coefficient_u(self) -> tuple[float, str]:
        """``ujn`` (avec fermeture) s'il existe, sinon ``uw`` (menuiserie nue)."""
        if self.ujn is not None:
            return self.ujn, "ujn"
        if self.uw is not None:
            return self.uw, "uw"
        raise ValueError(
            f"{self.description}: ni ujn ni uw dans donnee_intermediaire"
        )


class Porte(BaseModel):
    description: str
    reference: str | None = None
    surface_porte: float
    uporte: float
    b: float = 1.0


class PontThermique(BaseModel):
    description: str
    reference: str | None = None
    longueur_m: float = Field(description="linéaire l, en m")
    k: float = Field(description="coefficient linéique, W/m.K")
    pourcentage: float = Field(
        1.0,
        description="pourcentage_valeur_pont_thermique (1 ou 0,5 pour un refend partagé)",
    )
    b: float = 1.0


class DeperditionOfficielle(BaseModel):
    """Valeurs de la balise ``logement/sortie/deperdition``.
    ``deperdition_enveloppe`` du XML est le coefficient global publié par
    l'ADEME : transmission de l'enveloppe + renouvellement d'air.
    """

    valeurs: dict[str, float]

    def valeur(self, cle: str) -> float | None:
        return self.valeurs.get(cle)


class Dpe(BaseModel):
    numero_dpe: str | None = None
    surface_habitable_m2: float | None = None
    murs: list[Mur]
    planchers_bas: list[PlancherBas]
    planchers_hauts: list[PlancherHaut]
    baies: list[BaieVitree]
    portes: list[Porte]
    ponts_thermiques: list[PontThermique]
    deperdition: DeperditionOfficielle


def parse_dpe(source: SourceXml) -> Dpe:
    """Parse un DPE XML ADEME. ``source`` est un chemin ou un fichier binaire."""
    try:
        racine = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise DpeStructureError(
            "Le fichier fourni n'est pas un XML valide ou est corrompu."
        ) from exc

    _retirer_namespaces(racine)

    logement = racine.find("logement")
    if logement is None:
        raise DpeStructureError(
            "Balise <logement> absente : ce fichier ne correspond pas à un XML DPE ADEME."
        )

    enveloppe = logement.find("enveloppe")
    if enveloppe is None:
        version = racine.get("version", "inconnue")
        raise DpeStructureError(
            f"Balise <logement><enveloppe> absente du XML (version détectée : {version}). "
            "Ce fichier est trop ancien ou incompatible avec le moteur de calcul 3CL-DPE."
        )

    murs = [_mur(noeud) for noeud in _items(enveloppe, "mur_collection", "mur")]
    planchers_bas = [
        _plancher_bas(noeud)
        for noeud in _items(enveloppe, "plancher_bas_collection", "plancher_bas")
    ]
    planchers_hauts = [
        _plancher_haut(noeud)
        for noeud in _items(enveloppe, "plancher_haut_collection", "plancher_haut")
    ]
    baies = [
        _baie(noeud)
        for noeud in _items(enveloppe, "baie_vitree_collection", "baie_vitree")
    ]
    portes = [
        _porte(noeud) for noeud in _items(enveloppe, "porte_collection", "porte")
    ]
    ponts_thermiques = [
        _pont(noeud)
        for noeud in _items(
            enveloppe, "pont_thermique_collection", "pont_thermique"
        )
    ]

    if not any((murs, planchers_bas, planchers_hauts, baies, portes, ponts_thermiques)):
        carac = logement.find("caracteristique_generale")
        non_visite = _texte(carac, "appartement_non_visite")
        precision = (
            " (appartement non visité, DPE généré à partir d'un DPE immeuble)"
            if non_visite == "1"
            else ""
        )
        raise DpeStructureError(
            "La balise <logement><enveloppe> ne contient aucune paroi "
            f"(ni mur, plancher, baie, porte ou pont thermique){precision}. "
            "Impossible de recalculer les déperditions."
        )

    return Dpe(
        numero_dpe=_texte(racine, "numero_dpe"),
        surface_habitable_m2=_flottant(
            logement.find("caracteristique_generale"),
            "surface_habitable_logement",
        ),
        murs=murs,
        planchers_bas=planchers_bas,
        planchers_hauts=planchers_hauts,
        baies=baies,
        portes=portes,
        ponts_thermiques=ponts_thermiques,
        deperdition=_deperdition(logement.find("sortie")),
    )
# --------------------------------------------------------------------------
# Fonctions internes de lecture
# --------------------------------------------------------------------------


def _retirer_namespaces(racine: ET.Element) -> None:
    """Supprime les préfixes ``{namespace}`` pour pouvoir chercher par nom simple."""
    for element in racine.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]


def _items(enveloppe: ET.Element, collection: str, balise: str) -> Iterable[ET.Element]:
    """Éléments d'une collection, ou rien si la collection est absente."""
    noeud = enveloppe.find(collection)
    return [] if noeud is None else noeud.findall(balise)


def _texte(noeud: ET.Element | None, balise: str) -> str | None:
    if noeud is None:
        return None
    enfant = noeud.find(balise)
    if enfant is None or enfant.text is None or not enfant.text.strip():
        return None
    return enfant.text.strip()


def _flottant(noeud: ET.Element | None, balise: str) -> float | None:
    texte = _texte(noeud, balise)
    return None if texte is None else float(texte.replace(",", "."))


def _exiger(noeud: ET.Element | None, balise: str, contexte: str) -> float:
    valeur = _flottant(noeud, balise)
    if valeur is None:
        raise ValueError(f"{contexte}: balise {balise} absente")
    return valeur


def _entree_inter(noeud: ET.Element) -> tuple[ET.Element | None, ET.Element | None]:
    return noeud.find("donnee_entree"), noeud.find("donnee_intermediaire")


def _b(inter: ET.Element | None) -> float:
    """``b`` publié, y compris 0. Vaut 1 uniquement si la balise est absente."""
    valeur = _flottant(inter, "b")
    return 1.0 if valeur is None else valeur


def _description(entree: ET.Element | None, defaut: str) -> str:
    return _texte(entree, "description") or defaut


def _mur(noeud: ET.Element) -> Mur:
    entree, inter = _entree_inter(noeud)
    nom = _description(entree, "Mur")
    return Mur(
        description=nom,
        reference=_texte(entree, "reference"),
        surface_paroi_opaque=_exiger(entree, "surface_paroi_opaque", nom),
        umur=_exiger(inter, "umur", nom),
        b=_b(inter),
    )


def _plancher_bas(noeud: ET.Element) -> PlancherBas:
    entree, inter = _entree_inter(noeud)
    nom = _description(entree, "Plancher bas")
    return PlancherBas(
        description=nom,
        reference=_texte(entree, "reference"),
        surface_paroi_opaque=_exiger(entree, "surface_paroi_opaque", nom),
        upb=_flottant(inter, "upb"),
        upb_final=_flottant(inter, "upb_final"),
        b=_b(inter),
    )


def _plancher_haut(noeud: ET.Element) -> PlancherHaut:
    entree, inter = _entree_inter(noeud)
    nom = _description(entree, "Plancher haut")
    return PlancherHaut(
        description=nom,
        reference=_texte(entree, "reference"),
        surface_paroi_opaque=_exiger(entree, "surface_paroi_opaque", nom),
        uph=_exiger(inter, "uph", nom),
        b=_b(inter),
    )


def _baie(noeud: ET.Element) -> BaieVitree:
    entree, inter = _entree_inter(noeud)
    nom = _description(entree, "Baie vitrée")
    return BaieVitree(
        description=nom,
        reference=_texte(entree, "reference"),
        surface_totale_baie=_exiger(entree, "surface_totale_baie", nom),
        uw=_flottant(inter, "uw"),
        ujn=_flottant(inter, "ujn"),
        b=_b(inter),
    )


def _porte(noeud: ET.Element) -> Porte:
    entree, inter = _entree_inter(noeud)
    nom = _description(entree, "Porte")
    return Porte(
        description=nom,
        reference=_texte(entree, "reference"),
        surface_porte=_exiger(entree, "surface_porte", nom),
        uporte=_exiger(inter, "uporte", nom),
        b=_b(inter),
    )


def _pont(noeud: ET.Element) -> PontThermique:
    entree, inter = _entree_inter(noeud)
    nom = _description(entree, "Pont thermique")
    pourcentage = _flottant(entree, "pourcentage_valeur_pont_thermique")
    return PontThermique(
        description=nom,
        reference=_texte(entree, "reference"),
        longueur_m=_exiger(entree, "l", nom),
        k=_exiger(inter, "k", nom),
        pourcentage=1.0 if pourcentage is None else pourcentage,
        b=_b(inter),
    )


def _deperdition(sortie: ET.Element | None) -> DeperditionOfficielle:
    valeurs: dict[str, float] = {}
    bloc = None if sortie is None else sortie.find("deperdition")
    if bloc is not None:
        for enfant in bloc:
            if enfant.text and enfant.text.strip():
                try:
                    valeurs[enfant.tag] = float(enfant.text.strip())
                except ValueError:
                    pass
    return DeperditionOfficielle(valeurs=valeurs)