#!/bin/bash
#SBATCH --job-name=round
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1              
#SBATCH --ntasks-per-node=128   
#SBATCH --mem=0                # request ALL memory on each node (else SLURM caps at mem-per-cpu*ntasks)
#SBATCH --time=02:00:00        # fewer ranks total -> slower meshing
#SBATCH --error=round.err
#SBATCH --output=round.out
# Source OpenFOAM (Define the bashrc of your local openfoam location)

module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

# SnappyHex in parallel? ( 1 = Yes, 0 = No )
snapPar=1
# Ensure nprocs is defined to the correct number
nprocs=${SLURM_NTASKS:-128}   # match numberOfSubdomains to the actual allocation
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
[ -f geo/Mesh_Vegetation.obj ] && rsync -rhP geo/Mesh_Vegetation.obj constant/triSurface/   # porous-zone topoSet input (not snapped)
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
	srun snappyHexMesh -overwrite -parallel > logs/snappyHex.log 2>&1
	echo "Done with snappyHexMesh......"
	# Reconstruct the mesh
	echo "Reconstructing the mesh......"
	srun redistributePar -reconstruct -constant -parallel > logs/reconstruct.log 2>&1
	echo "Copy the mesh to savedMesh folder....."
	rsync -r constant/polyMesh savedMesh/ 2>/dev/null || true
	# Run check mesh for sanity
	echo "Running checkmesh utility......."
	srun checkMesh -parallel > logs/checkMesh.log 2>&1
	# Porous vegetation: build the 'vegetationZone' cellZone on the decomposed mesh
	if [ -f system/topoSetDict ] && [ -f constant/triSurface/Mesh_Vegetation.obj ]; then
		echo "Building vegetationZone cellZone (porous canopy)......"
		srun topoSet -parallel > logs/topoSet.log 2>&1
	fi
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
