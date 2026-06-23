import trimesh

#mesh_files = ['Mesh_Buildings.obj','Mesh_Ocean.obj', 'Mesh_Terrain.obj', 'Mesh_Vegetation.obj', 'Mesh_Water.obj']
mesh_files = ['Mesh_Buildings.obj', 'Mesh_Terrain.obj', 'Mesh_Vegetation.obj', 'Mesh_Water.obj']
scale = 1.0 #1.0/0.3048
for mymeshfile in mesh_files:
    print(f"Working on {mymeshfile}")
    mesh = trimesh.load(mymeshfile)
    #mesh.vertices *= scale  # Scale the vertices
    #mesh.export(mymeshfile)  # Save the scaled mesh back to the file
    print(f"Bounding Box Minimum: {mesh.bounds[0]}")
    print(f"Bounding Box Maximum: {mesh.bounds[1]}")
