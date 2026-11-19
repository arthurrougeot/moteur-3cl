"""Lecture d'un XML de DPE (schéma ADEME 3CL) vers des modèles typés.
Les balises optionnelles (``ujn``, ``upb_final``, ``b``, pourcentage de pont
thermique, champs de ventilation) restent absentes plutôt que de faire échouer
le parse. Les coefficients nécessaires au calcul sont vérifiés au moment du calcul.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import IO, Iterable, Literal, Union

from pydantic import BaseModel, Field

SourceXml = Union[str, Path, IO[bytes]]
StatutVersion = Literal["stabilisee", "avant_stabilisation"]

# Modèles DPE neufs dans le référentiel ADEME (2 = DPE neuf logement, 3 = DPE neuf tertiaire)
_MODELES_DPE_NEUF = {"2", "3"}


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


class Ventilation(BaseModel):
    description: str | None = None
    reference: str | None = None
    tv_debits_ventilation_id: int | None = Field(
        None,
        description="Index (1 à 38) de la table officielle des débits 3CL",
    )
    enum_type_ventilation_id: int | None = None
    surface_ventile: float | None = Field(None, description="Sh ventilée, en m²")
    plusieurs_facade_exposee: int | None = Field(
        None,
        description="0 = une seule façade exposée, 1 = plusieurs façades exposées",
    )
    q4pa_conv: float | None = Field(
        None,
        description="Perméabilité conventionnelle sous 4 Pa, m³/(h.m²)",
    )
    hvent_officiel: float | None = None
    hperm_officiel: float | None = None


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
    version_xsd: str | None = None
    statut_version: StatutVersion = "avant_stabilisation"
    modele_dpe_id: str | None = None
    surface_habitable_m2: float | None = None
    source_surface_habitable: str | None = None
    hsp_m: float | None = Field(None, description="Hauteur moyenne sous plafond, en m")
    murs: list[Mur]
    planchers_bas: list[PlancherBas]
    planchers_hauts: list[PlancherHaut]
    baies: list[BaieVitree]
    portes: list[Porte]
    ponts_thermiques: list[PontThermique]
    ventilations: list[Ventilation] = Field(default_factory=list)
    deperdition: DeperditionOfficielle


def _tuple_version(version_str: str | None) -> tuple[int, ...] | None:
    """Convertit une chaîne de version (ex. '2.4') en tuple d'entiers (2, 4)."""
    if not version_str:
        return None
    morceaux = re.findall(r"\d+", version_str)
    if not morceaux:
        return None
    return tuple(int(m) for m in morceaux)


def _evaluer_version(version_str: str | None) -> StatutVersion:
    """Retourne ``stabilisee`` pour les versions >= 2.1, sinon ``avant_stabilisation``."""
    parsed = _tuple_version(version_str)
    if parsed is None:
        return "avant_stabilisation"
    if parsed >= (2, 1):
        return "stabilisee"
    return "avant_stabilisation"


def parse_dpe(source: SourceXml) -> Dpe:
    """Parse un DPE XML ADEME. ``source`` est un chemin ou un fichier binaire."""
    try:
        racine = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise DpeStructureError(
            "Le fichier fourni n'est pas un XML valide ou est corrompu."
        ) from exc

    _retirer_namespaces(racine)

    numero = _texte(racine, "numero_dpe")
    if racine.tag.lower() == "audit" or (numero and numero.upper().startswith("A")):
        raise DpeStructureError(
            "Ce fichier correspond à un Audit énergétique (et non à un DPE). "
            "Les audits sont exclus du périmètre de ce moteur."
        )

    logement = racine.find("logement")
    if logement is None:
        raise DpeStructureError(
            "Balise <logement> absente : ce fichier ne correspond pas à un XML DPE ADEME."
        )

    admin = racine.find("administratif")
    modele_dpe_id = _texte(admin, "enum_modele_dpe_id")
    version_xsd = _texte(admin, "enum_version_id") or racine.get("version")

    if modele_dpe_id in _MODELES_DPE_NEUF:
        raise DpeStructureError(
            "DPE neuf exclu : un DPE neuf ne contient pas les informations nécessaires "
            "au calcul 3CL d'enveloppe classique (les données proviennent du RSET/RSEE "
            "de l'étude thermique, et <enveloppe> peut être vide ou absente)."
        )

    enveloppe = logement.find("enveloppe")
    if enveloppe is None:
        raise DpeStructureError(
            f"Balise <logement><enveloppe> absente du XML (version détectée : {version_xsd or 'inconnue'}). "
            "Si le fichier est un DPE neuf, il ne contient pas les informations de calcul "
            "3CL d'enveloppe classique (données issues du RSET/RSEE) ; sinon le fichier "
            "est trop ancien ou incompatible."
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
    ventilations = [
        _ventilation(noeud)
        for noeud in _items(logement, "ventilation_collection", "ventilation")
    ]

    carac = logement.find("caracteristique_generale")

    if not any((murs, planchers_bas, planchers_hauts, baies, portes, ponts_thermiques)):
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

    sh_logement = _flottant(carac, "surface_habitable_logement")
    sh_immeuble = _flottant(carac, "surface_habitable_immeuble")
    if sh_logement is not None:
        surface_habitable = sh_logement
        source_sh = "surface_habitable_logement"
    elif sh_immeuble is not None:
        surface_habitable = sh_immeuble
        source_sh = "surface_habitable_immeuble"
    else:
        surface_habitable = None
        source_sh = None

    return Dpe(
        numero_dpe=numero,
        version_xsd=version_xsd,
        statut_version=_evaluer_version(version_xsd),
        modele_dpe_id=modele_dpe_id,
        surface_habitable_m2=surface_habitable,
        source_surface_habitable=source_sh,
        hsp_m=_flottant(carac, "hsp"),
        murs=murs,
        planchers_bas=planchers_bas,
        planchers_hauts=planchers_hauts,
        baies=baies,
        portes=portes,
        ponts_thermiques=ponts_thermiques,
        ventilations=ventilations,
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


def _items(parent: ET.Element, collection: str, balise: str) -> Iterable[ET.Element]:
    """Éléments d'une collection, ou rien si la collection est absente."""
    noeud = parent.find(collection)
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


def _entier(noeud: ET.Element | None, balise: str) -> int | None:
    texte = _texte(noeud, balise)
    if texte is None:
        return None
    try:
        return int(float(texte.replace(",", ".")))
    except ValueError:
        return None


def _entier_booleen(noeud: ET.Element | None, balise: str) -> int | None:
    """Lit un indicateur binaire XML (``0`` ou ``1``)."""
    texte = _texte(noeud, balise)
    if texte is None:
        return None
    bas = texte.lower()
    if bas in ("0", "false"):
        return 0
    if bas in ("1", "true"):
        return 1
    valeur = _entier(noeud, balise)
    return valeur if valeur in (0, 1) else None


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


def _ventilation(noeud: ET.Element) -> Ventilation:
    entree, inter = _entree_inter(noeud)
    return Ventilation(
        description=_texte(entree, "description"),
        reference=_texte(entree, "reference"),
        tv_debits_ventilation_id=_entier(entree, "tv_debits_ventilation_id"),
        enum_type_ventilation_id=_entier(entree, "enum_type_ventilation_id"),
        surface_ventile=_flottant(entree, "surface_ventile"),
        plusieurs_facade_exposee=_entier_booleen(entree, "plusieurs_facade_exposee"),
        q4pa_conv=_flottant(inter, "q4pa_conv"),
        hvent_officiel=_flottant(inter, "hvent"),
        hperm_officiel=_flottant(inter, "hperm"),
    )


def _deperdition(sortie: ET.Element | None) -> DeperditionOfficielle:
    valeurs: dict[str, float] = {}
    bloc = None if sortie is None else sortie.find("deperdition")
    if bloc is not None:
        for enfant in bloc:
            if enfant.text and enfant.text.strip():
                try:
                    valeurs[enfant.tag] = float(enfant.text.strip().replace(",", "."))
                except ValueError:
                    pass
    return DeperditionOfficielle(valeurs=valeurs)