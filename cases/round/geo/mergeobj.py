import trimesh
import glob
import os

def merge_objs(obj_files, output_file='merged.obj'):
    """
    Merge multiple OBJ files into a single mesh and save to output_file.

    Parameters:
        obj_files (list of str): List of .obj file paths to merge.
        output_file (str): Path to output merged .obj file.
    """
    meshes = []

    for file in obj_files:
        mesh = trimesh.load(file, force='mesh')
        if mesh.is_empty:
            print(f"⚠️ Skipping empty mesh: {file}")
            continue
        meshes.append(mesh)

    # Merge all meshes
    combined = trimesh.util.concatenate(meshes)

    # Export to single OBJ
    combined.export(output_file)
    print(f"✅ Merged OBJ saved: {output_file}")


if __name__ == '__main__':
    # Automatically grab all .obj files in current directory
    obj_files = sorted(glob.glob('*.obj'))

    if len(obj_files) < 2:
        print("Need at least two .obj files to merge.")
    else:
        merge_objs(obj_files, output_file='merged_terrain.stl')
