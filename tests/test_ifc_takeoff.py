import unittest

from scripts.ifc_takeoff import answer, build_model, catalog_titles


HEADER = """ISO-10303-21;
HEADER;FILE_SCHEMA(('IFC2X3'));ENDSEC;DATA;
#1=IFCPROJECT('project',$,'Example',$,$,$,$,(),#2);
#2=IFCUNITASSIGNMENT((#3,#4));
#3=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#4=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
#10=IFCBUILDINGSTOREY('l1',$,'Level 1',$,$,$,$,$,.ELEMENT.,0.);
#11=IFCSPACE('room',$,'R-1',$,$,$,#100,'Room O''Brien; (lab, west)',.ELEMENT.,.INTERNAL.,$);
#12=IFCRELAGGREGATES('s',$,$,$,#10,(#11));
#13=IFCDOOR('door',$,'D-1',$,$,$,#101,$,2.,1.);
#14=IFCRELCONTAINEDINSPATIALSTRUCTURE('d',$,$,$,(#13),#11);
#15=IFCFLOWTERMINAL('light',$,'L-1',$,$,$,$,$);
#16=IFCLIGHTFIXTURETYPE('lamp-type',$,'Light type',$,$,$,$,$,$,.DIRECTIONSOURCE.);
#17=IFCRELDEFINESBYTYPE('t',$,$,$,(#15),#16);
#18=IFCSTAIRFLIGHT('flight',$,'Flight',$,$,$,#102,$,$,$,$,$);
"""
ROOM = "What is the net floor area of the room 'Room O'Brien; (lab, west) (R-1)' on 'Level 1', in m²?"
TOTAL = "What is the total net floor area of all rooms (spaces) on 'Level 1', in m²?"
ASSIGN = """
#20=IFCELEMENTQUANTITY('q',$,'Qto_SpaceBaseQuantities',$,$,(#21));
#22=IFCRELDEFINESBYPROPERTIES('assign',$,$,$,(#11),#20);
"""


def model(extra=""):
    return build_model((HEADER+extra+"\nENDSEC;END-ISO-10303-21;").encode())


class IfcTakeoffTests(unittest.TestCase):
    def test_title_and_credit_come_from_the_same_raw_ifc_table_row(self):
        doc = b"| demo.ifc | Demo title | CC0 | Author | https://example.test |\n| demo.pdf | PDF | CC0 | Author | source |"
        self.assertEqual(catalog_titles(doc), {"demo.ifc":"Demo title"})
        self.assertEqual(catalog_titles(doc,with_attribution=True)["demo.ifc"], {
            "work":"Demo title","license":"CC0","credit":"Author","sourceUrl":"https://example.test"})

    def test_counts_follow_storey_through_space_and_retain_source(self):
        m = model()
        r = answer(m, "How many doors are shown on the floor plan of 'Level 1'?")
        self.assertEqual((r["status"],r["unit"],r["answer"]), ("answered","count",1))
        proof, = r["evidence"]
        self.assertEqual((proof["step_id"], proof["global_id"], proof["geometry_ids"]), (13,"door",[101]))
        self.assertEqual(proof["relation_ids"], [14,12])
        self.assertTrue(proof["source_line"].startswith("#13=IFCDOOR("))
        self.assertEqual(answer(m,"How many stairs are there in the model?")["answer"],0)
        self.assertEqual(answer(m,"How many doors are shown on the floor plan of 'Unknown'?")["status"],"unsupported")

    def test_paraphrases_and_explicit_scope(self):
        m = model(ASSIGN + "#21=IFCQUANTITYAREA('NetFloorArea',$,$,12.);")
        for prompt in ("Count the doors", "How many doors?", "How many doors are on Level 1?",
                       "Count the doors on 'Level 1'", "How many doors are there in the model 'Example'?"):
            with self.subTest(prompt=prompt):
                self.assertEqual(answer(m,prompt)["answer"],1)
        for prompt in ("Count the doors on Level 3", "Count the doors over 1 m wide",
                       "How many doors are there in the model 'Other building'?",
                       "How many doors are there in the model and only on Level 3?"):
            with self.subTest(prompt=prompt):
                self.assertEqual(answer(m,prompt)["status"],"unsupported")
        self.assertEqual(answer(m, "What is the net floor area of room R-1 on Level 1?")["answer"],12)
        self.assertEqual(answer(m, "What is the net floor area of room X on Level 1?")["status"],"unsupported")

    def test_sideways_space_sweep_projects_the_vertical_section(self):
        shape = """
        #100=IFCPRODUCTDEFINITIONSHAPE($,$,(#101));
        #101=IFCSHAPEREPRESENTATION(#777,'Body','SweptSolid',(#102));
        #102=IFCEXTRUDEDAREASOLID(#103,#110,#104,2000.);
        #103=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#105);
        #104=IFCDIRECTION((0.,0.,1.));#105=IFCPOLYLINE((#111,#112,#113,#114,#111));
        #110=IFCAXIS2PLACEMENT3D(#99,#120,#121);
        #120=IFCDIRECTION((1.,0.,0.));#121=IFCDIRECTION((0.,-1.,0.));
        #111=IFCCARTESIANPOINT((0.,0.));#112=IFCCARTESIANPOINT((4000.,0.));
        #113=IFCCARTESIANPOINT((4000.,3000.));#114=IFCCARTESIANPOINT((0.,3000.));
        """
        result = answer(model(shape),ROOM)
        self.assertEqual(result["answer"],8)
        self.assertIn(110,result["evidence"][0]["geometry_ids"])

    def test_ifc2x3_generic_terminal_uses_occurrence_type_assignment(self):
        result = answer(model(), "How many light fixtures are there in the model?")
        self.assertEqual(result["answer"],1)
        item, = result["evidence"]
        self.assertEqual((item["step_id"], item["type_id"], item["relation_ids"]), (15,16,[17]))

    def test_explicit_conversion_unit_overrides_project_unit(self):
        m = model(ASSIGN+"""
        #21=IFCQUANTITYAREA('NetFloorArea',$,#25,50.);
        #24=IFCMEASUREWITHUNIT(IFCAREAMEASURE(0.09290304),#4);
        #25=IFCCONVERSIONBASEDUNIT(#26,.AREAUNIT.,'SQUARE FOOT',#24);
        """)
        result = answer(m, ROOM)
        self.assertAlmostEqual(result["answer"], 50*.09290304)
        item, = result["evidence"]
        self.assertEqual(item["quantity_id"],21)
        self.assertEqual(item["unit_id"],25)
        self.assertEqual(item["relation_ids"],[12,22])
        self.assertIn("NetFloorArea",item["quantity_source_line"])

    def test_area_prefix_is_squared_and_step_multiline_respects_quotes(self):
        m = model(ASSIGN+"""
        /* a misleading #3=IFCSPACE('foo;'); */
        #21=IFCQUANTITYAREA(
          'NetFloorArea','comment /* not syntax */, ;',#26,3000000.);
        #26=IFCSIUNIT(*,.AREAUNIT.,.MILLI.,.SQUARE_METRE.);
        """)
        self.assertEqual(answer(m,ROOM)["answer"],3)
        self.assertEqual(answer(m,TOTAL)["answer"],3)

    def test_geometry_uses_inner_profile_instead_of_gross_export_property(self):
        both = """
        #20=IFCELEMENTQUANTITY('old',$,'GSA Space Areas',$,$,(#21));
        #21=IFCQUANTITYAREA('GSA BIM Area',$,$,999.);
        #22=IFCRELDEFINESBYPROPERTIES('a',$,$,$,(#11),#20);
        #100=IFCPRODUCTDEFINITIONSHAPE($,$,(#101));
        #101=IFCSHAPEREPRESENTATION(#777,'Body','SweptSolid',(#102));
        #102=IFCEXTRUDEDAREASOLID(#103,$,#104,2500.);
        #103=IFCARBITRARYPROFILEDEFWITHVOIDS(.AREA.,$,#105,(#106));
        #104=IFCDIRECTION((0.,0.,1.));
        #105=IFCPOLYLINE((#111,#112,#113,#114,#111));
        #106=IFCPOLYLINE((#121,#122,#123,#124,#121));
        #111=IFCCARTESIANPOINT((0.,0.));#112=IFCCARTESIANPOINT((4000.,0.));
        #113=IFCCARTESIANPOINT((4000.,3000.));#114=IFCCARTESIANPOINT((0.,3000.));
        #121=IFCCARTESIANPOINT((1000.,1000.));#122=IFCCARTESIANPOINT((2000.,1000.));
        #123=IFCCARTESIANPOINT((2000.,2000.));#124=IFCCARTESIANPOINT((1000.,2000.));
        """
        result = answer(model(both), ROOM)
        self.assertEqual((result["answer"],result["method"]), (11,"IFC room footprint"))
        item, = result["evidence"]
        self.assertEqual(item["geometry_ids"],[100,101,102,103,105,106])
        self.assertEqual(item["unit_id"],3)
        self.assertIn("PROFILEDEFWITHVOIDS",item["geometry_source_line"])
        self.assertIsNone(item["quantity_id"])
        tilted = both.replace("(0.,0.,1.)", "(1.,0.,1.)")
        self.assertEqual(answer(model(tilted),ROOM)["status"],"unsupported")

    def test_closed_surface_uses_floor_not_other_horizontal_faces(self):
        geometry = """
        #100=IFCPRODUCTDEFINITIONSHAPE($,$,(#201));
        #201=IFCSHAPEREPRESENTATION(#99,'Body','SurfaceModel',(#202));
        #202=IFCFACEBASEDSURFACEMODEL((#203));#203=IFCCONNECTEDFACESET((#204,#205,#206,#207,#208));
        #204=IFCFACE((#211));#205=IFCFACE((#212));#206=IFCFACE((#213));#207=IFCFACE((#214));#208=IFCFACE((#215));
        #211=IFCFACEOUTERBOUND(#221,.T.);#212=IFCFACEOUTERBOUND(#222,.T.);#213=IFCFACEOUTERBOUND(#223,.T.);
        #214=IFCFACEOUTERBOUND(#224,.T.);#215=IFCFACEOUTERBOUND(#225,.T.);
        #221=IFCPOLYLOOP((#231,#232,#233));#222=IFCPOLYLOOP((#234,#235,#236));
        #223=IFCPOLYLOOP((#231,#232,#235,#234));#224=IFCPOLYLOOP((#232,#233,#236,#235));
        #225=IFCPOLYLOOP((#233,#231,#234,#236));
        #231=IFCCARTESIANPOINT((0.,0.,0.));#232=IFCCARTESIANPOINT((4000.,0.,0.));#233=IFCCARTESIANPOINT((0.,3000.,0.));
        #234=IFCCARTESIANPOINT((0.,0.,2500.));#235=IFCCARTESIANPOINT((4000.,0.,2500.));#236=IFCCARTESIANPOINT((0.,3000.,2500.));
        """
        result = answer(model(geometry), ROOM)
        self.assertEqual(result["answer"],6)
        self.assertIn(204, result["evidence"][0]["geometry_ids"])
        self.assertNotIn(205, result["evidence"][0]["geometry_ids"])

    def test_net_quantity_and_complete_storey_required(self):
        gross = "#21=IFCQUANTITYAREA('GrossFloorArea',$,$,16.);"
        self.assertEqual(answer(model(ASSIGN+gross),ROOM)["status"],"unsupported")
        extra = """
        #30=IFCSPACE('room2',$,'R-2',$,$,$,$,'Other',.ELEMENT.,.INTERNAL.,$);
        #31=IFCRELAGGREGATES('agg2',$,$,$,#10,(#30));
        """
        m = model(ASSIGN + "#21=IFCQUANTITYAREA('NetFloorArea',$,$,12.);" + extra)
        self.assertEqual(answer(m,ROOM)["answer"],12)
        self.assertEqual(answer(m,TOTAL)["status"],"unsupported")

    def test_conflicting_net_areas_and_unknown_units_abstain(self):
        props = ASSIGN.replace("(#21)", "(#21,#29)")
        rows = "#21=IFCQUANTITYAREA('NetFloorArea',$,$,12.);#29=IFCQUANTITYAREA('NetFloorArea',$,$,14.);"
        self.assertEqual(answer(model(props + rows), ROOM)["status"],"unsupported")
        self.assertEqual(answer(model(ASSIGN+"#21=IFCQUANTITYAREA('NetFloorArea',$,#99,12.);"),ROOM)["status"],"unsupported")


if __name__ == "__main__":
    unittest.main()
