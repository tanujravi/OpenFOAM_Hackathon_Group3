# Shared rules for both temporal strategies (quasi-steady + transient).
# Expects these globals already defined by the including Snakefile:
#   FLOW, TOOLS, WORK, SCRIPTS, PY, NP, PAR, IT2, HALF

rule carve_mesh:
    input:
        os.path.join(FLOW, "constant", "polyMesh", "boundary")
    output:
        touch(os.path.join(WORK, ".mesh_carved"))
    shell:
        r'bash "{SCRIPTS}/carve_mesh.sh" "{FLOW}" "{TOOLS}" {HALF} "{PY}"'

rule flow_hour:
    input:
        os.path.join(WORK, ".mesh_carved")
    output:
        os.path.join(WORK, "flow", "h{hour}", "frozen", "U")
    threads: NP
    shell:
        r'bash "{SCRIPTS}/run_flow_hour.sh" {wildcards.hour} "{FLOW}" "{TOOLS}" "{WORK}" {NP} {PAR} {IT2} "{PY}"'
