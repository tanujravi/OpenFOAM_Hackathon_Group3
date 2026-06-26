#!/bin/bash
#SBATCH --job-name=round
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=4              # more nodes, FEWER ranks/node => more RAM per rank (snappy OOM fix)
#SBATCH --ntasks-per-node=12   # 12/node ~2.5GB/rank on a 32GB node; raise nodes (not this) for speed
#SBATCH --mem=0                # request ALL memory on each node (else SLURM caps at mem-per-cpu*ntasks)
#SBATCH --time=03:00:00        # fewer ranks total -> slower meshing
#SBATCH --error=round.err
#SBATCH --output=round.out
# Source OpenFOAM (Define the bashrc of your local openfoam location)

module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

# SnappyHex in parallel? ( 1 = Yes, 0 = No )
snapPar=1
# Ensure nprocs is defined to the correct number
nprocs=${SLURM_NTASKS:-96}   # match numberOfSubdomains to the actual allocation
# Surfaces to mesh (recentred frame). Guimaraes small domain: buildings + terrain
# only. No water surface is provided; canopy is a porous zone, not a meshed wall.
outMesh1="geo/Mesh_Buildings.obj"
outMesh2="geo/Mesh_Terrain.obj"
# Check if logs directory exists
if [ -d "logs" ]; then
	echo "Starting script...."
else
	mkdir logs
	echo "`logs` missing, creating it now....."
fi
# First fix the numebr of processors in the system/decomposeParDict file
sed_command="s/numberOfSubdomains [0-9]\+;/numberOfSubdomains ${nprocs};/g"
eval "sed -i \"$sed_command\" system/decomposeParDict"
# Copy the file to the right location
rsync -rhP $outMesh1 constant/triSurface/
rsync -rhP $outMesh2 constant/triSurface/
echo "Done with copying the geometry...."
# Run surfaceFeatures
#surfaceFeatures > logs/surfaceFeatures.log
surfaceFeatureExtract > logs/surfaceFeatures.log
echo "Done with surface features....."
# Generate the blockMeshDict
m4 system/blockMeshDict.m4 > system/blockMeshDict
blockMesh > logs/blockMesh.log
echo "Done with blockMesh......"
# Decompose the mesh for snappyHex in parallel if user prompts
if [ $snapPar ]; then
	echo "Decomposing the mesh......."
	decomposePar -force > logs/decomposePar.log 2>&1
	# Generate the snappyHexMesh
	echo "To follow the progress for snappyHexMesh, read logs/snappyHex.log....."
	#snappyHexMesh -overwrite > logs/snappyHex.log
	srun snappyHexMesh -parallel > logs/snappyHex.log 2>&1
	echo "Done with snappyHexMesh......"
	# Reconstruct the mesh
	echo "Reconstructing the mesh......"
	reconstructParMesh -constant > logs/reconstructSnappyMesh.log 2>&1
	echo "Copy the mesh to savedMesh folder....."
	rsync -r 1 2 savedMesh/
	# Run check mesh for sanity
	echo "Running checkmesh utility......."
	srun checkMesh -latestTime -parallel > logs/checkMesh.log 2>&1
else
	echo "Snappy Hex Mesh runs in serial......"
	# Generate the snappyHexMesh
	echo "To follow the progress for snappyHexMesh, read logs/snappyHex.log....."
	#snappyHexMesh -overwrite > logs/snappyHex.log
	snappyHexMesh > logs/snappyHex.log
	echo "Done with snappyHexMesh......"
	# Run check mesh for sanity
	echo "Running checkmesh utility......."
	checkMesh -latestTime > logs/checkMesh.log
fi
echo "Done with runallgeo.sh...."
