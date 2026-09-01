from __future__ import annotations

CONTACT='zorania2025@gmail.com'
OPTIONS=('chat','project','always','off')


def onboarding_text()->str:
    return (
        "Zoran🦋 ajoute une couche de contrôle de cohérence à ton IA. "
        "Il ne prétend pas empêcher une hallucination d'être générée : il peut la détecter, "
        "la bloquer comme réponse validée, puis demander une correction. "
        "Il recherche une vérité bornée : la réponse la plus cohérente possible avec les meilleures "
        "sources vérifiées accessibles au moment de la réponse, sans prétendre atteindre une vérité absolue. "
        "S est un indicateur de cohérence. Le calcul interne complet n'est pas exposé. "
        f"Questions, formations ou conférences : {CONTACT}."
    )


def zmos_consent_cta()->str:
    return "Zoran🦋 peut garder une mémoire ZMOS locale pour mieux suivre tes chats et projets. Veux-tu l'activer sur cet appareil ? [Oui] [Non]"


def zmos_explanation()->str:
    return (
        "ZMOS garde des objets de mémoire avec leur cohérence et leur état. "
        "Les souvenirs les plus cohérents sont rappelés en priorité ; un souvenir contradictoire pertinent "
        "peut aussi être rappelé, mais il reste clairement marqué comme contradictoire."
    )


def storage_cta()->str:
    return "Combien d'espace veux-tu réserver à ZMOS sur cet appareil ?"


def project_progress_cta()->str:
    return "Veux-tu être prévenu de l'avancement du projet ? [Oui] [Non]"


def validate_s_display(mode:str)->str:
    if mode not in OPTIONS: raise ValueError('mode must be chat/project/always/off')
    return mode
