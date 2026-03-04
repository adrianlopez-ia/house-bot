"""Pure data: seed sites and search queries.

No side effects, no imports beyond models.  Easy to extend by appending
to the two lists below.
"""
from __future__ import annotations

from db.models import Site, Zone, SiteType

SEED_SITES: tuple[Site, ...] = (
    # ── Plataformas de cooperativas ───────────────────────────────────
    Site(url="https://cooptima.es/cooperativas-de-viviendas/madrid",
         name="Cooptima Madrid", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    Site(url="https://aurora-homes.es/cooperativas-de-viviendas-en-madrid/",
         name="Aurora Homes", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    Site(url="https://concovi.org/",
         name="CONCOVI", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    # ── Portales inmobiliarios ────────────────────────────────────────
    Site(url="https://www.idealista.com/obra-nueva/madrid/norte/",
         name="Idealista Obra Nueva Norte", zone=Zone.NORTE, site_type=SiteType.PORTAL),
    Site(url="https://www.idealista.com/obra-nueva/madrid/este/",
         name="Idealista Obra Nueva Este", zone=Zone.ESTE, site_type=SiteType.PORTAL),
    Site(url="https://www.idealista.com/obra-nueva/madrid/oeste/",
         name="Idealista Obra Nueva Oeste", zone=Zone.OESTE, site_type=SiteType.PORTAL),
    Site(url="https://www.fotocasa.es/es/obra-nueva/viviendas/madrid-capital/todas-las-zonas/l",
         name="Fotocasa Obra Nueva Madrid", zone=Zone.TODAS, site_type=SiteType.PORTAL),
    # ── Cooperativas conocidas ────────────────────────────────────────
    Site(url="https://www.larimarviviendas.es/",
         name="Larimar Viviendas", zone=Zone.TODAS, site_type=SiteType.COOPERATIVA),
    Site(url="https://www.dfrviviendas.es/",
         name="DFR Viviendas", zone=Zone.TODAS, site_type=SiteType.COOPERATIVA),
    Site(url="https://www.grupovia.net/",
         name="Grupo Via", zone=Zone.TODAS, site_type=SiteType.COOPERATIVA),
    # ── Constructoras ─────────────────────────────────────────────────
    Site(url="https://www.aelca.es/viviendas/madrid/",
         name="Aelca Madrid", zone=Zone.NORTE, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.metrovacesa.com/promociones-obra-nueva/madrid",
         name="Metrovacesa Madrid", zone=Zone.TODAS, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.neinor.com/promociones/madrid",
         name="Neinor Homes Madrid", zone=Zone.TODAS, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.viacelere.com/obra-nueva/madrid",
         name="Via Celere Madrid", zone=Zone.TODAS, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.habitat.es/es/obra-nueva/madrid",
         name="Habitat Inmobiliaria Madrid", zone=Zone.ESTE, site_type=SiteType.CONSTRUCTORA),
    Site(url="https://www.arpada.es/promociones/",
         name="Arpada Promociones", zone=Zone.OESTE, site_type=SiteType.CONSTRUCTORA),
)

SEARCH_QUERIES: tuple[dict[str, str], ...] = (
    {"query": "cooperativa vivienda Madrid norte 2025 2026", "zone": "norte"},
    {"query": "cooperativa vivienda Madrid este Vallecas Rivas 2025 2026", "zone": "este"},
    {"query": "cooperativa vivienda Madrid oeste Pozuelo Majadahonda 2025 2026", "zone": "oeste"},
    {"query": "constructora obra nueva Madrid norte Alcobendas San Sebastian Reyes", "zone": "norte"},
    {"query": "constructora obra nueva Madrid este Coslada Torrejon", "zone": "este"},
    {"query": "constructora obra nueva Madrid oeste Boadilla Villanueva", "zone": "oeste"},
    {"query": "nueva promocion vivienda cooperativa Madrid", "zone": "todas"},
    {"query": "cooperativa vivienda joven Madrid precios", "zone": "todas"},
    {"query": "promociones vivienda protegida Madrid norte este oeste", "zone": "todas"},
)
