from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from .models import (Capteur, DecisionIrrigation, EtapeMission, Irrigation, Mesure, Mission,
                     Parcelle, Robot, Zone)


class BaseDonneesTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("t", password="x")
        self.parcelle = Parcelle.objects.create(code="P01", nom="Test", superficie_m2=100)
        self.z1 = Zone.objects.create(parcelle=self.parcelle, code="Z1", seuil_min_pct=30)
        self.z2 = Zone.objects.create(parcelle=self.parcelle, code="Z2")
        self.robot = Robot.objects.create(identifiant="R1")
        self.cap = Capteur.objects.create(robot=self.robot, type_capteur="HUMIDITE_SOL", reference="c1")
        self.mission = Mission.objects.create(robot=self.robot, cree_par=self.user)
        self.etape = EtapeMission.objects.create(mission=self.mission, ordre=1, zone=self.z1)

    # --- utilitaires -------------------------------------------------------
    def demarrer(self):
        self.mission.statut = "EN_COURS"
        self.mission.date_debut = timezone.now()
        self.mission.save()

    def mesure(self, uid="u1", **kw):
        data = dict(message_uid=uid, robot=self.robot, capteur=self.cap, mission=self.mission,
                    etape=self.etape, zone=self.z1, humidite_pct=20, validite="VALIDE",
                    horodatage_mesure=timezone.now())
        data.update(kw)
        return Mesure.objects.create(**data)

    def autorisation(self):
        self.demarrer()
        return DecisionIrrigation.objects.create(
            mesure=self.mesure(), zone=self.z1, seuil_utilise_pct=30, decision="ARROSAGE_AUTORISE")

    def refuse(self):
        """Contexte : l'opération doit être rejetée par la base."""
        from contextlib import contextmanager

        @contextmanager
        def ctx():
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    yield
        return ctx()

    # --- référentiel -------------------------------------------------------
    def test_code_zone_unique_par_parcelle(self):
        with self.refuse():
            Zone.objects.create(parcelle=self.parcelle, code="Z1")

    def test_suppression_parcelle_protegee(self):
        with self.assertRaises(ProtectedError):
            self.parcelle.delete()

    def test_superficie_positive(self):
        with self.refuse():
            Parcelle.objects.create(code="P02", nom="Neg", superficie_m2=-5)

    # --- missions et mesures -----------------------------------------------
    def test_mesure_refusee_si_mission_planifiee(self):
        with self.refuse():
            self.mesure()

    def test_mesure_mauvaise_zone_refusee(self):
        self.demarrer()
        with self.refuse():
            self.mesure(zone=self.z2)          # l'étape concerne Z1

    def test_mesure_doublon_refuse(self):
        self.demarrer()
        self.mesure("dup")
        with self.refuse():
            self.mesure("dup")

    def test_mesure_valide_hors_bornes_refusee(self):
        self.demarrer()
        with self.refuse():
            self.mesure(humidite_pct=150)

    def test_mesure_invalide_sans_motif_refusee(self):
        self.demarrer()
        with self.refuse():
            self.mesure(validite="INVALIDE", humidite_pct=None, motif_invalidite="")

    def test_mesure_immuable(self):
        self.demarrer()
        m = self.mesure()
        m.humidite_pct = 99
        with self.refuse():
            m.save()

    def test_transition_mission_illegale(self):
        self.demarrer()
        self.mission.statut = "PLANIFIEE"
        with self.refuse():
            self.mission.save()

    # --- décision et irrigation --------------------------------------------
    def test_arrosage_interdit_si_mesure_invalide(self):
        self.demarrer()
        m = self.mesure(validite="INVALIDE", humidite_pct=None, motif_invalidite="capteur débranché")
        with self.refuse():
            DecisionIrrigation.objects.create(mesure=m, zone=self.z1, seuil_utilise_pct=30,
                                              decision="ARROSAGE_AUTORISE")
        # la décision INTERDIT, elle, est acceptée
        DecisionIrrigation.objects.create(mesure=m, zone=self.z1, seuil_utilise_pct=30,
                                          decision="INTERDIT")

    def test_irrigation_sans_autorisation_refusee(self):
        self.demarrer()
        d = DecisionIrrigation.objects.create(mesure=self.mesure(), zone=self.z1,
                                              seuil_utilise_pct=30, decision="AUCUNE_ACTION")
        with self.refuse():
            Irrigation.objects.create(commande_uid="c1", decision=d, zone=self.z1,
                                      robot=self.robot, duree_max_s=10)

    def test_irrigation_plafond_systeme(self):
        d = self.autorisation()
        with self.refuse():       # 45 s <= 60 s (CHECK) mais > 30 s (paramètre système)
            Irrigation.objects.create(commande_uid="c2", decision=d, zone=self.z1,
                                      robot=self.robot, duree_max_s=45)

    def test_irrigation_valide_puis_commande_rejouee(self):
        d = self.autorisation()
        Irrigation.objects.create(commande_uid="c3", decision=d, zone=self.z1,
                                  robot=self.robot, duree_max_s=20)
        with self.refuse():
            Irrigation.objects.create(commande_uid="c3", decision=d, zone=self.z1,
                                      robot=self.robot, duree_max_s=20)

