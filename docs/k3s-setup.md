# k3s setup for Pulse v2

This document covers the local k3s installation used during v2 development.
A future migration to AWS uses the same steps on an EC2 instance.

## Local setup (current)

k3s is installed directly on the development VM. Single-node cluster.

### Install

```bash
curl -sfL https://get.k3s.io | sh -
```

This installs k3s as a systemd service, enabled at boot. Service status:

```bash
sudo systemctl status k3s
```

### Configure kubectl

The k3s install creates a kubeconfig at `/etc/rancher/k3s/k3s.yaml` owned by root.
Copy it to the user's home so kubectl works without sudo:

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
chmod 600 ~/.kube/config
```

Verify:

```bash
kubectl get nodes
```

### What's included with k3s by default

- **Traefik** — ingress controller, listens on port 80/443
- **CoreDNS** — cluster DNS resolver
- **local-path-provisioner** — storage class for PersistentVolumeClaims
- **metrics-server** — needed for `kubectl top`

These are all installed automatically and run in the `kube-system` namespace.

## Future AWS migration

When ready to migrate to AWS:

1. Add a k3s module call to `terraform/main.tf`:

```hcl
   module "k3s" {
     source            = "./modules/ec2"
     name              = "pulse-v2-k3s"
     instance_type     = "t3.small"   # 2GB RAM minimum for k3s + workloads
     key_name          = module.networking.key_name
     security_group_id = module.networking.security_group_id
   }
```

2. Open additional ports in the security group (NodePort range, k3s API):
   - 6443 (Kubernetes API)
   - 30000-32767 (NodePort range)

3. `terraform apply`, then run the install command above on the new EC2 via SSH or Ansible.

4. To use the cluster from your local machine, copy the kubeconfig from the EC2 and edit the `server:` line to use the EC2's public IP.

## Cost considerations

t3.small in eu-central-1 is approximately $15/month. EBS storage adds another ~$3/month.
Total roughly $18/month while the cluster is running. Stop or destroy when not actively
developing to avoid charges.

## Useful commands

```bash
kubectl get nodes                       # cluster status
kubectl get pods --all-namespaces       # everything running
kubectl get svc                         # services
kubectl logs <pod-name>                 # pod logs
kubectl describe pod <pod-name>         # detailed pod info
kubectl delete deployment <name>        # remove a deployment
sudo systemctl restart k3s              # restart k3s if needed
```

## Uninstall

If you need to wipe k3s and start over:

```bash
/usr/local/bin/k3s-uninstall.sh
```