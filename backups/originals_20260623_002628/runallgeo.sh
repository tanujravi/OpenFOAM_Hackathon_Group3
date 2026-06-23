#!/bin/bash
#SBATCH --job-name=round
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=96
#SBATCH --time=00:15:00
#SBATCH --error=round.err
#SBATCH --output=round.out
# Source OpenFOAM (Define the bashrc of your local openfoam location)

module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

# SnappyHex in parallel? ( 1 = Yes, 0 = No )
snapPar=1
# Ensure nprocs is defined to the correct number
nprocs=96
# Name of the output stl
outMesh1="geo/Mesh_Buildings.obj"
outMesh2="geo/Mesh_Terrain.obj"
outMesh3="geo/Mesh_Vegetation.obj"
outMesh4="geo/Mesh_Water.obj"
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
rsync -rhP $outMesh3 constant/triSurface/
rsync -rhP $outMesh4 constant/triSurface/
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
	mpirun -np $nprocs snappyHexMesh -parallel > logs/snappyHex.log 2>&1
	echo "Done with snappyHexMesh......"
	# Reconstruct the mesh
	echo "Reconstructing the mesh......"
	reconstructParMesh -constant > logs/reconstructSnappyMesh.log 2>&1
	echo "Copy the mesh to savedMesh folder....."
	rsync -r 1 2 savedMesh/
	# Run check mesh for sanity
	echo "Running checkmesh utility......."
	mpirun -np $nprocs checkMesh -latestTime -parallel > logs/checkMesh.log 2>&1
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
