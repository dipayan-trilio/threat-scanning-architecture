package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/sirupsen/logrus"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	"sigs.k8s.io/controller-runtime/pkg/webhook"

	threatv1 "github.com/trilioData/threat-scanning-architecture/api/v1"
	scaninstancecontroller "github.com/trilioData/threat-scanning-architecture/controllers/scaninstance"
	targetcontroller "github.com/trilioData/threat-scanning-architecture/controllers/target"
	"github.com/trilioData/threat-scanning-architecture/internal"
	targetwebhook "github.com/trilioData/threat-scanning-architecture/pkg/webhook/target"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(threatv1.AddToScheme(scheme))
}

func main() {
	var enableLeaderElection bool
	var enableWebhook bool
	var webhookPort int
	var webhookCertDir string

	flag.BoolVar(&enableLeaderElection, "leader-elect", false,
		"Enable leader election for controller manager. "+
			"Enabling this will ensure there is only one active controller manager.")
	flag.BoolVar(&enableWebhook, "enable-webhook", false,
		"Enable webhook server for target validation.")
	flag.IntVar(&webhookPort, "webhook-port", 9443,
		"Port for the webhook server to listen on.")
	flag.StringVar(&webhookCertDir, "webhook-cert-dir", "/tmp/k8s-webhook-server/serving-certs",
		"Directory containing TLS certificates for the webhook server.")

	opts := zap.Options{
		Development: true,
	}
	opts.BindFlags(flag.CommandLine)
	flag.Parse()

	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	// Setup logrus logger
	logger := logrus.New()
	logger.SetFormatter(&logrus.JSONFormatter{})
	logger.SetOutput(os.Stdout)
	logger.SetLevel(logrus.InfoLevel)

	setupLog.Info("Starting Threat Scanning Target Controller")
	setupLog.Info(fmt.Sprintf("Installation namespace: %s", internal.GetInstallNamespace()))

	mgrOptions := ctrl.Options{
		Scheme:           scheme,
		LeaderElection:   enableLeaderElection,
		LeaderElectionID: "target-controller-leader-election",
	}

	// Configure webhook server if enabled
	if enableWebhook {
		mgrOptions.WebhookServer = webhook.NewServer(webhook.Options{
			Port:    webhookPort,
			CertDir: webhookCertDir,
		})
	}

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), mgrOptions)
	if err != nil {
		setupLog.Error(err, "unable to start manager")
		os.Exit(1)
	}

	// Setup Target Controller
	targetReconciler := &targetcontroller.Reconciler{
		Client:    mgr.GetClient(),
		Log:       logger.WithField("controller", "Target"),
		Scheme:    mgr.GetScheme(),
		Recorder:  mgr.GetEventRecorderFor("target-controller"),
		APIReader: mgr.GetAPIReader(),
	}

	if err = targetReconciler.SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "Target")
		os.Exit(1)
	}

	// Setup ScanInstance Controller
	scanInstanceReconciler := &scaninstancecontroller.Reconciler{
		Client:    mgr.GetClient(),
		Log:       logger.WithField("controller", "ScanInstance"),
		Scheme:    mgr.GetScheme(),
		Recorder:  mgr.GetEventRecorderFor("scaninstance-controller"),
		APIReader: mgr.GetAPIReader(),
	}

	if err = scanInstanceReconciler.SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "ScanInstance")
		os.Exit(1)
	}

	// Setup webhook if enabled
	if enableWebhook {
		setupLog.Info("Setting up webhook server")
		targetValidator := targetwebhook.NewTargetValidator(mgr.GetClient())
		mgr.GetWebhookServer().Register("/validate-threatscanning-trilio-io-v1-target",
			&webhook.Admission{Handler: targetValidator})
		setupLog.Info("Webhook server configured successfully")
	}

	// Setup health and readiness checks
	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	setupLog.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		setupLog.Error(err, "problem running manager")
		os.Exit(1)
	}
}
