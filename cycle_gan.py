import itertools
import torch
from torch import nn
from torchvision.utils import save_image

from utils import EpochTracker
from networks import CycleGanDiscriminator, CycleGanResnetGenerator


class CycleGAN:

    def __init__(self, options, device, file_prefix, learning_rate, beta1, train=False):
        self.name = "CycleGAN"
        self.lambda_A = 10.0  # weight for cycle-loss A->B->A
        self.lambda_B = 10.0  # weight for cycle-loss B->A->B

        self.is_train = train
        self.device = device
        self.file_prefix = file_prefix

        self.epoch_tracker = EpochTracker(file_prefix + "epoch.txt")

        self.GenA = CycleGanResnetGenerator().to(device)
        self.GenB = CycleGanResnetGenerator().to(device)

        self.real_A = self.real_B = self.fake_A = self.fake_B = self.new_A = self.new_B = None

        if train:
            self.DisA = CycleGanDiscriminator().to(device)
            self.DisB = CycleGanDiscriminator().to(device)

            # define loss functions
            self.criterionGAN = nn.BCELoss().to(device)
            self.criterionCycle = nn.L1Loss()
            self.criterionIdt = nn.L1Loss()

            # initialize optimizers
            self.optimizer_g = torch.optim.Adam(itertools.chain(self.GenA.parameters(), self.GenB.parameters()),
                                                lr=learning_rate, betas=(beta1, 0.999))
            self.optimizer_d = torch.optim.Adam(itertools.chain(self.DisA.parameters(), self.DisB.parameters()),
                                                lr=learning_rate, betas=(beta1, 0.999))
            self.optimizers = [self.optimizer_g, self.optimizer_d]

            self.loss_disA = self.loss_disB = self.loss_cycle_A = 0
            self.loss_cycle_B = self.loss_genA = self.loss_genB = 0
            self.loss_G = 0

        if self.epoch_tracker.file_exists:
            self.GenA.load_state_dict(torch.load(file_prefix + 'generator_a.pth'))
            self.GenB.load_state_dict(torch.load(file_prefix + 'generator_b.pth'))

            if train:
                self.DisA.load_state_dict(torch.load(file_prefix + 'discriminator_a.pth'))
                self.DisB.load_state_dict(torch.load(file_prefix + 'discriminator_b.pth'))


    def set_input(self, real_A, real_B):
        self.real_A = real_A.to(self.device)
        self.real_B = real_B.to(self.device)

    def forward(self):
        self.fake_B = self.GenA(self.real_A)
        self.new_A = self.GenB(self.fake_B)

        self.fake_A = self.GenB(self.real_B)
        self.new_B = self.GenA(self.fake_A)

    def backward_d(self, netD, real, fake):
        predict_real = netD(real)
        loss_d_real = self.criterionGAN(predict_real, True)

        predict_fake = netD(fake.detach())
        loss_d_fake = self.criterionGAN(predict_fake, False)

        loss_d = (loss_d_real + loss_d_fake) * 0.5
        loss_d.backward()

        return loss_d

    def backward_g(self):
        self.loss_genA = self.criterionGAN(self.DisA(self.fake_B), True)
        self.loss_genB = self.criterionGAN(self.DisB(self.fake_A), True)

        # Forward cycle loss
        self.loss_cycle_A = self.criterionCycle(self.new_A, self.real_A) * self.lambda_A
        # Backward cycle loss
        self.loss_cycle_B = self.criterionCycle(self.new_B, self.real_B) * self.lambda_B

        # combined loss
        self.loss_G = self.loss_genA + self.loss_genB + self.loss_cycle_A + self.loss_cycle_B

        self.loss_G.backward()

    def train(self):
        # forward
        self.forward()

        # GenA and GenB
        self.set_requires_grad([self.DisA, self.DisB], False)
        self.optimizer_g.zero_grad()
        self.backward_g()
        self.optimizer_g.step()

        # DisA and DisB
        self.set_requires_grad([self.DisA, self.DisB], True)
        self.optimizer_d.zero_grad()

        # backward Dis A
        self.loss_disA = self.backward_d(self.DisA, self.real_B, self.fake_B)

        # backward Dis B
        self.loss_disB = self.backward_d(self.DisB, self.real_A, self.fake_A)

        self.optimizer_d.step()

    def test(self):
        with torch.no_grad():
            self.forward()

    def save_progress(self, path, epoch, iteration):
        img_sample = torch.cat((self.real_A.data, self.fake_A.data, self.real_B.data, self.fake_B.data), -2)
        save_image(img_sample, path + "{}_{}.png".format(epoch, iteration), nrow=5, normalize=True)

        torch.save(self.GenA.state_dict(), self.file_prefix + "generator_a.pth")
        torch.save(self.GenB.state_dict(), self.file_prefix + "generator_b.pth")
        torch.save(self.DisA.state_dict(), self.file_prefix + "discriminator_a.pth")
        torch.save(self.DisB.state_dict(), self.file_prefix + "discriminator_b.pth")
        self.epoch_tracker.write(epoch, iteration)

    @staticmethod
    def set_requires_grad(nets, requires_grad=False):
        for net in nets:
            if net is not None:
                for param in net.parameters():
                    param.requires_grad = requires_grad
